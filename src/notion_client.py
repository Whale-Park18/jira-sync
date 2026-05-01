from typing import Any, List

import requests
from loguru import logger

from env import Env
from config import FieldMapping
from jira_client import Issue
from api_urls import NotionApi
from notion_schema import Schema


class NotionDatabase:
    """Notion API 클라이언트 - Schema를 Notion DB에 upsert."""

    def __init__(self, env: Env) -> None:
        self.api_key = env.notion_api_key
        self.data_source_id = env.notion_data_source_id

    def _headers(self) -> dict:
        """공통 Notion API 요청 헤더."""
        return {
            "Notion-Version": NotionApi.NOTION_VERSION,
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _to_notion_property(value: Any, notion_type: str) -> dict:
        """값을 Notion 프로퍼티 포맷으로 변환.

        Args:
            value: Jira에서 추출한 원시 값
            notion_type: title | rich_text | select | status | date | url
        """
        if notion_type == "title":
            return {"title": [{"text": {"content": str(value or "")}}]}
        if notion_type == "rich_text":
            return {"rich_text": [{"text": {"content": str(value or "")}}]}
        if notion_type == "select":
            return {"select": {"name": str(value)} if value else None}
        if notion_type == "status":
            return {"status": {"name": str(value)} if value else None}
        if notion_type == "date":
            return {"date": {"start": str(value)} if value else None}
        if notion_type == "url":
            return {"url": str(value) if value else None}
        # 알 수 없는 타입은 rich_text로 폴백
        return {"rich_text": [{"text": {"content": str(value or "")}}]}

    def query(self, notion_query: dict = None) -> dict:
        """Notion DB를 단일 페이지 조회하여 원시 응답 반환.

        Args:
            notion_query: sync_config.yaml의 notion_query. filter/sorts/page_size는 body,
                          filter_properties는 URL 쿼리 파라미터로 분리 전송.
        """
        # filter_properties는 URL 쿼리 파라미터, 나머지는 request body
        body = {k: v for k, v in (notion_query or {}).items() if v is not None}
        filter_properties = body.pop("filter_properties", None)

        response = requests.post(
            url=NotionApi.query_data_source_url(self.data_source_id),
            headers=self._headers(),
            json=body,
            params={"filter_properties": filter_properties} if filter_properties else None,
        )

        if response.status_code != 200:
            logger.error(f"Notion query 오류 {response.status_code}: {response.text}")
            return {}

        return response.json()

    def _lookup_pages(self, notion_query: dict, title_property: str, scan_mode: str = "filtered") -> List[dict]:
        """upsert용 페이지 조회.

        - scan_mode="full": filter 제거 → 필터 밖 페이지(예: 완료 상태)까지 포함하여 중복 판별
        - scan_mode="filtered"(기본): filter 유지 → 빠르지만 필터 범위 밖 페이지는 중복 판별 대상에서 제외
        - filter_properties에 title 컬럼 자동 포함
        - has_more/next_cursor 기반 페이지네이션 처리
        """
        # scan_mode == "full" 일 때만 filter 키 제거. 그 외(기본 "filtered")는 filter 유지하여 조회 속도 확보
        lookup_q = {
            k: v
            for k, v in (notion_query or {}).items()
            if not (scan_mode == "full" and k == "filter") and v is not None
        }

        # filter_properties가 지정된 경우 title 컬럼 누락 방지
        filter_props = lookup_q.get("filter_properties")
        if filter_props is not None and title_property not in filter_props:
            lookup_q["filter_properties"] = list(filter_props) + [title_property]

        all_pages: List[dict] = []
        start_cursor: str | None = None

        while True:
            body = {k: v for k, v in lookup_q.items() if k != "filter_properties"}
            if start_cursor:
                body["start_cursor"] = start_cursor

            filter_properties = lookup_q.get("filter_properties")
            response = requests.post(
                url=NotionApi.query_data_source_url(self.data_source_id),
                headers=self._headers(),
                json=body,
                params={"filter_properties": filter_properties} if filter_properties else None,
            )

            if response.status_code != 200:
                logger.error(f"Notion lookup 오류 {response.status_code}: {response.text}")
                return []

            data = response.json()
            all_pages.extend(data.get("results", []))

            if not data.get("has_more"):
                break

            start_cursor = data.get("next_cursor")
            logger.debug(f"다음 페이지 조회 중 (현재까지 {len(all_pages)}건)")

        return all_pages

    def upsert(
        self,
        issues: List[Issue],
        mappings: List[FieldMapping],
        notion_query: dict = None,
        scan_mode: str = "filtered",
    ) -> None:
        """Jira 이슈를 Notion DB에 upsert (title 기준 find → update or create).

        Args:
            issues: JiraClient로 조회한 이슈 목록
            mappings: mapping_config.yaml의 mappings
            notion_query: Notion 조회 시 적용할 필터/정렬 body
            scan_mode: "filtered"(기본)면 notion_query.filter를 그대로 lookup에 적용.
                       "full"이면 lookup 단계에서 filter를 제거하고 전체 스캔 (필터 범위 밖 페이지도
                       중복 판별 대상에 포함).
        """
        # notion_type: title 인 매핑이 upsert 키
        title_mapping = next((m for m in mappings if m.notion_type == "title"), None)
        if title_mapping is None:
            logger.error("title 타입 매핑이 없어 upsert를 수행할 수 없습니다.")
            return

        # 기존 Notion 페이지 조회 → title값: page_id 딕셔너리 구성
        # scan_mode를 _lookup_pages에 전달하여 filter 적용 여부 제어
        all_pages = self._lookup_pages(notion_query, title_mapping.notion_property, scan_mode=scan_mode)
        page_lookup: dict[str, str] = {}
        for page in all_pages:
            title_prop = page.get("properties", {}).get(title_mapping.notion_property, {})
            title_texts = title_prop.get("title", [])
            if title_texts:
                key = title_texts[0].get("text", {}).get("content", "")
                page_lookup[key] = page["id"]

        # 이슈별 upsert
        for issue in issues:
            schema = Schema.from_issue(issue, mappings)
            logger.debug(f"[{issue.key}] {schema.properties}")

            # Notion 프로퍼티 포맷으로 변환
            properties = {
                m.notion_property: self._to_notion_property(schema.properties[m.notion_property], m.notion_type)
                for m in mappings
            }

            title_value = schema.properties.get(title_mapping.notion_property)

            if title_value in page_lookup:
                # 기존 페이지 업데이트
                page_id = page_lookup[title_value]
                response = requests.patch(
                    url=NotionApi.update_page_url(page_id),
                    headers=self._headers(),
                    json={"properties": properties},
                )
                action = "updated"
            else:
                # 신규 페이지 생성
                response = requests.post(
                    url=NotionApi.create_page_url(),
                    headers=self._headers(),
                    json={"parent": {"data_source_id": self.data_source_id}, "properties": properties},
                )
                action = "created"

            if response.status_code not in (200, 201):
                logger.error(f"[{issue.key}] Notion {action} 실패 {response.status_code}: {response.text}")
            else:
                logger.info(f"[{issue.key}] Notion {action}")
