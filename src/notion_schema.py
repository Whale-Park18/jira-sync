from dataclasses import dataclass, field
from typing import Any, List

from config import FieldMapping
from jira_client import Issue


def _resolve_field(issue: Issue, jira_field: str) -> Any:
    """jira_field 점 표기법으로 Issue에서 값 추출.

    key는 최상위 필드, 나머지는 fields.* 경로로 접근.
    """
    if jira_field == "key":
        return issue.key

    # fields.summary → ["summary"], fields.status.name → ["status", "name"]
    parts = jira_field.removeprefix("fields.").split(".")
    value = issue.fields
    for part in parts:
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


@dataclass
class Schema:
    """Notion DB에 upsert할 단일 페이지의 프로퍼티 집합.

    mappings는 사용자 설정(mapping_config.yaml)에 따라 달라지므로
    고정 필드 대신 dict로 관리.
    """
    # notion_property 이름 → 값 (예: {"issue": "PROJ-1", "제목": "버그 수정"})
    properties: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_issue(cls, issue: Issue, mappings: List[FieldMapping]) -> "Schema":
        """Issue와 FieldMapping 목록으로 Schema 생성.

        Args:
            issue: Jira 이슈
            mappings: mapping_config.yaml의 mappings 항목
        Returns:
            notion_property → 값으로 채워진 Schema 인스턴스
        """
        properties = {
            mapping.notion_property: _resolve_field(issue, mapping.jira_field)
            for mapping in mappings
        }

        return cls(properties=properties)
