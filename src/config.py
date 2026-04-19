from dataclasses import dataclass
from typing import Any, Dict, List
import yaml


@dataclass(frozen=True)
class FieldMapping:
    """Jira 필드 하나를 Notion 프로퍼티로 변환하는 규칙."""
    jira_field: str       # 점 표기법 지원 (예: fields.status.name)
    notion_property: str  # Notion DB 컬럼명
    notion_type: str      # title | rich_text | select | date | url | status


@dataclass(frozen=True)
class QueryConfig:
    """Jira 이슈 조회 파라미터."""
    jql: str
    max_results: int
    fields: List[str]


@dataclass(frozen=True)
class SyncConfig:
    """mapping_config.yaml 전체를 파싱한 결과."""
    query: QueryConfig
    notion_query: Dict[str, Any]  # Notion DB 조회 시 사용할 필터/정렬 body
    mappings: List[FieldMapping]


_VALID_DIRECTIONS = {"ascending", "descending"}
_VALID_NOTION_TYPES = {"title", "rich_text", "select", "status", "date", "url"}


def _validate_notion_query(nq: Dict[str, Any]) -> None:
    """notion_query 구조 및 값 유효성 검사.

    Raises:
        ValueError: 유효하지 않은 값 발견 시
    """
    if not isinstance(nq, dict):
        raise ValueError("notion_query는 dict 타입이어야 합니다.")

    # filter
    if "filter" in nq and nq["filter"] is not None:
        if not isinstance(nq["filter"], dict):
            raise ValueError("notion_query.filter는 dict 타입이어야 합니다.")

    # sorts
    if "sorts" in nq and nq["sorts"] is not None:
        if not isinstance(nq["sorts"], list):
            raise ValueError("notion_query.sorts는 list 타입이어야 합니다.")
        for i, sort in enumerate(nq["sorts"]):
            if not isinstance(sort, dict):
                raise ValueError(f"notion_query.sorts[{i}]는 dict 타입이어야 합니다.")
            if "property" not in sort:
                raise ValueError(f"notion_query.sorts[{i}]에 property가 없습니다.")
            if "direction" not in sort:
                raise ValueError(f"notion_query.sorts[{i}]에 direction이 없습니다.")
            if sort["direction"] not in _VALID_DIRECTIONS:
                raise ValueError(
                    f"notion_query.sorts[{i}].direction은 {_VALID_DIRECTIONS} 중 하나여야 합니다. "
                    f"현재 값: '{sort['direction']}'"
                )

    # page_size
    if "page_size" in nq and nq["page_size"] is not None:
        if not isinstance(nq["page_size"], int) or not (1 <= nq["page_size"] <= 100):
            raise ValueError("notion_query.page_size는 1~100 사이의 정수여야 합니다.")

    # filter_properties
    if "filter_properties" in nq and nq["filter_properties"] is not None:
        if not isinstance(nq["filter_properties"], list):
            raise ValueError("notion_query.filter_properties는 list 타입이어야 합니다.")
        for i, prop in enumerate(nq["filter_properties"]):
            if not isinstance(prop, str):
                raise ValueError(f"notion_query.filter_properties[{i}]는 문자열이어야 합니다.")


def _validate_mappings(mappings: List[Dict[str, Any]]) -> None:
    """mappings 구조 및 값 유효성 검사.

    Raises:
        ValueError: 유효하지 않은 값 발견 시
    """
    title_count = sum(1 for m in mappings if m.get("notion_type") == "title")
    if title_count == 0:
        raise ValueError("mappings에 notion_type이 'title'인 항목이 하나 이상 있어야 합니다.")
    if title_count > 1:
        raise ValueError("mappings에 notion_type이 'title'인 항목은 하나여야 합니다.")

    for i, m in enumerate(mappings):
        for key in ("jira_field", "notion_property", "notion_type"):
            if not m.get(key):
                raise ValueError(f"mappings[{i}].{key}가 누락되었습니다.")
        if m["notion_type"] not in _VALID_NOTION_TYPES:
            raise ValueError(
                f"mappings[{i}].notion_type은 {_VALID_NOTION_TYPES} 중 하나여야 합니다. "
                f"현재 값: '{m['notion_type']}'"
            )


def load_config(path: str) -> SyncConfig:
    """YAML 파일을 읽어 SyncConfig 객체로 반환.

    Args:
        path: mapping_config.yaml 경로
    Returns:
        파싱된 SyncConfig 인스턴스
    Raises:
        KeyError: 필수 키 누락 시
    """
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    query_raw = raw["jira_query"]
    query = QueryConfig(
        jql=query_raw["jql"],
        max_results=query_raw["maxResults"],
        fields=query_raw["fields"],
    )

    notion_query: Dict[str, Any] = raw.get("notion_query", {})
    _validate_notion_query(notion_query)

    mappings_raw = raw["mappings"]
    _validate_mappings(mappings_raw)
    mappings = [
        FieldMapping(
            jira_field=m["jira_field"],
            notion_property=m["notion_property"],
            notion_type=m["notion_type"],
        )
        for m in mappings_raw
    ]

    return SyncConfig(query=query, notion_query=notion_query, mappings=mappings)
