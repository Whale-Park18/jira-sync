from typing import Any, List

import requests
from loguru import logger

from env import Env
from config import FieldMapping
from jira_client import Issue
from api_urls import NotionApi
from notion_schema import Schema


# Notion 복합 필터(or) 조건 수 한도(~100)에 맞춘 키 배치 크기
_KEY_FILTER_BATCH = 100


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

    def _query_all_pages(self, body: dict, filter_properties: list = None) -> List[dict]:
        """단일 조회 조건(body)으로 has_more/next_cursor 페이지네이션을 모두 순회하여 페이지 누적.

        Args:
            body: data_source query request body (filter/sorts/page_size 등). start_cursor는 내부에서 주입.
            filter_properties: 응답에 포함할 컬럼 (URL 쿼리 파라미터로 전송).
        Returns:
            조회된 페이지 리스트 (오류 시 빈 리스트)
        """
        all_pages: List[dict] = []
        start_cursor: str | None = None

        while True:
            req_body = dict(body)
            if start_cursor:
                req_body["start_cursor"] = start_cursor

            response = requests.post(
                url=NotionApi.query_data_source_url(self.data_source_id),
                headers=self._headers(),
                json=req_body,
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

    @staticmethod
    def _log_pages(all_pages: List[dict]) -> None:
        """조회된 페이지 전체 내용을 DEBUG로 출력 (응답 리스트 가시화)."""
        logger.debug(f"Notion 조회 페이지 목록 ({len(all_pages)}건):")
        for page in all_pages:
            logger.debug(f"    [{page.get('id')}] {page.get('properties')}")

    def _lookup_pages(self, notion_query: dict, title_property: str, scan_mode: str = "filtered") -> List[dict]:
        """upsert용 페이지 조회 (notion_query 기반).

        - scan_mode="full": filter 제거 → 필터 밖 페이지(예: 완료 상태)까지 포함하여 중복 판별
        - scan_mode="filtered"(기본): filter 유지 → 빠르지만 필터 범위 밖 페이지는 중복 판별 대상에서 제외
        - filter_properties에 title 컬럼 자동 포함
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

        # body(filter/sorts/page_size 등)와 filter_properties(URL 파라미터) 분리 후 페이지네이션 조회
        body = {k: v for k, v in lookup_q.items() if k != "filter_properties"}
        all_pages = self._query_all_pages(body, lookup_q.get("filter_properties"))

        self._log_pages(all_pages)
        return all_pages

    def _lookup_pages_by_keys(self, title_property: str, keys: List[str]) -> List[dict]:
        """JQL 결과 이슈 키만 콕 집어 조회 (title equals 조건을 or로 묶어 배치 질의).

        notion_query.filter와 무관하게 해당 키의 기존 페이지를 모두 찾으므로,
        필터 밖(예: 완료 상태) 페이지 누락으로 인한 중복 생성을 방지한다.
        Notion 복합 필터 조건 수 한도에 맞춰 _KEY_FILTER_BATCH 단위로 나눠 요청한다.

        Args:
            title_property: upsert 키가 되는 title 컬럼명
            keys: 조회할 title 값(이슈 키) 목록
        Returns:
            매칭된 기존 페이지 리스트
        """
        # falsy 제거 + 순서 유지 중복 제거 (불필요한 조건/요청 감소)
        unique_keys = [k for k in dict.fromkeys(keys) if k]
        if not unique_keys:
            return []

        all_pages: List[dict] = []
        # _KEY_FILTER_BATCH 단위 배치 → 배치당 1회(+페이지네이션) 요청
        for start in range(0, len(unique_keys), _KEY_FILTER_BATCH):
            batch = unique_keys[start:start + _KEY_FILTER_BATCH]
            body = {
                "filter": {
                    "or": [{"property": title_property, "title": {"equals": k}} for k in batch]
                },
                "page_size": 100,
            }
            # title 컬럼만 응답에 포함하여 페이로드 최소화
            all_pages.extend(self._query_all_pages(body, [title_property]))

        self._log_pages(all_pages)
        return all_pages

    def upsert(
        self,
        issues: List[Issue],
        mappings: List[FieldMapping],
        notion_query: dict = None,
        scan_mode: str = "keys",
        dry_run: bool = False,
    ) -> None:
        """Jira 이슈를 Notion DB에 upsert (title 기준 find → update or create).

        Args:
            issues: JiraClient로 조회한 이슈 목록
            mappings: mapping_config.yaml의 mappings
            notion_query: Notion 조회 시 적용할 필터/정렬 body (keys 모드에서는 미사용)
            scan_mode: "keys"(기본)면 JQL 결과 이슈 키만 or-필터로 조회 (필터 밖 페이지도 매칭, 효율적).
                       "filtered"면 notion_query.filter를 그대로 lookup에 적용.
                       "full"이면 lookup 단계에서 filter를 제거하고 전체 스캔 (필터 범위 밖 페이지도
                       중복 판별 대상에 포함).
            dry_run: True면 Notion 조회(lookup)는 수행하되 PATCH/POST 쓰기는 생략하고
                     이슈별 update/created 예측만 로그로 출력.
        """
        # notion_type: title 인 매핑이 upsert 키
        title_mapping = next((m for m in mappings if m.notion_type == "title"), None)
        if title_mapping is None:
            logger.error("title 타입 매핑이 없어 upsert를 수행할 수 없습니다.")
            return

        # 이슈별 Schema를 1회만 변환 (lookup 키 추출 + 이후 루프에서 재사용)
        schemas = [Schema.from_issue(issue, mappings) for issue in issues]
        title_values = [s.properties.get(title_mapping.notion_property) for s in schemas]

        # 기존 Notion 페이지 조회 → title값: page_id 딕셔너리 구성
        if scan_mode == "keys":
            # JQL 결과 키만 콕 집어 조회 (notion_query.filter 무시, 중복 방지 + 효율적)
            all_pages = self._lookup_pages_by_keys(title_mapping.notion_property, title_values)
        else:
            # filtered/full: notion_query 기반 조회 (scan_mode로 filter 적용 여부 제어)
            all_pages = self._lookup_pages(notion_query, title_mapping.notion_property, scan_mode=scan_mode)
        page_lookup: dict[str, str] = {}
        for page in all_pages:
            title_prop = page.get("properties", {}).get(title_mapping.notion_property, {})
            title_texts = title_prop.get("title", [])
            if title_texts:
                key = title_texts[0].get("text", {}).get("content", "")
                page_lookup[key] = page["id"]

        # 이슈별 upsert (precomputed schema 재사용)
        for issue, schema in zip(issues, schemas):
            logger.debug(f"[{issue.key}] {schema.properties}")

            # Notion 프로퍼티 포맷으로 변환
            properties = {
                m.notion_property: self._to_notion_property(schema.properties[m.notion_property], m.notion_type)
                for m in mappings
            }

            title_value = schema.properties.get(title_mapping.notion_property)

            # update/created 판별 (dry-run·실모드 공통)
            action = "updated" if title_value in page_lookup else "created"

            # dry-run: 실제 쓰기 없이 예측 결과만 로그
            if dry_run:
                logger.info(f"[{issue.key}] Notion {action} (dry-run)")
                continue

            if title_value in page_lookup:
                # 기존 페이지 업데이트
                page_id = page_lookup[title_value]
                response = requests.patch(
                    url=NotionApi.update_page_url(page_id),
                    headers=self._headers(),
                    json={"properties": properties},
                )
            else:
                # 신규 페이지 생성
                response = requests.post(
                    url=NotionApi.create_page_url(),
                    headers=self._headers(),
                    json={"parent": {"data_source_id": self.data_source_id}, "properties": properties},
                )

            if response.status_code not in (200, 201):
                logger.error(f"[{issue.key}] Notion {action} 실패 {response.status_code}: {response.text}")
            else:
                logger.info(f"[{issue.key}] Notion {action}")
