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
        """Notion DB를 조회하여 페이지 목록 반환.

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

    def upsert(self, issues: List[Issue], mappings: List[FieldMapping], notion_query: dict = None) -> None:
        """Jira 이슈를 Notion DB에 upsert (title 기준 find → update or create).

        Args:
            issues: JiraClient로 조회한 이슈 목록
            mappings: mapping_config.yaml의 mappings
            notion_query: Notion 조회 시 적용할 필터/정렬 body
        """
        # notion_type: title 인 매핑이 upsert 키
        title_mapping = next((m for m in mappings if m.notion_type == "title"), None)
        if title_mapping is None:
            logger.error("title 타입 매핑이 없어 upsert를 수행할 수 없습니다.")
            return

        # 기존 Notion 페이지 조회 → title값: page_id 딕셔너리 구성
        existing = self.query(notion_query)
        page_lookup: dict[str, str] = {}
        for page in existing.get("results", []):
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
