import pytest
from jira_client import Issue
from config import FieldMapping
from notion_schema import _resolve_field, Schema


# ──────────────────────────────────────────────
# _resolve_field
# ──────────────────────────────────────────────

class TestResolveField:

    def _issue(self, fields=None):
        return Issue(key="TEST-1", fields=fields or {})

    def test_key(self):
        assert _resolve_field(self._issue(), "key") == "TEST-1"

    def test_top_level_field(self):
        issue = self._issue({"summary": "버그 수정"})
        assert _resolve_field(issue, "fields.summary") == "버그 수정"

    def test_nested_field(self):
        issue = self._issue({"status": {"name": "In Progress"}})
        assert _resolve_field(issue, "fields.status.name") == "In Progress"

    def test_deep_nested_field(self):
        issue = self._issue({"priority": {"iconUrl": "http://example.com", "name": "High"}})
        assert _resolve_field(issue, "fields.priority.name") == "High"

    def test_missing_field_returns_none(self):
        assert _resolve_field(self._issue(), "fields.duedate") is None

    def test_missing_nested_field_returns_none(self):
        issue = self._issue({"status": {"name": "Done"}})
        assert _resolve_field(issue, "fields.status.nonexistent") is None

    def test_intermediate_not_dict_returns_none(self):
        """중간 노드가 dict가 아닌 경우 None 반환."""
        issue = self._issue({"status": "string_not_dict"})
        assert _resolve_field(issue, "fields.status.name") is None


# ──────────────────────────────────────────────
# Schema.from_issue
# ──────────────────────────────────────────────

class TestSchema:

    def _mappings(self):
        return [
            FieldMapping(jira_field="key", notion_property="issue", notion_type="title"),
            FieldMapping(jira_field="fields.summary", notion_property="제목", notion_type="rich_text"),
            FieldMapping(jira_field="fields.status.name", notion_property="상태", notion_type="status"),
        ]

    def test_from_issue_basic(self):
        issue = Issue(key="PROJ-1", fields={"summary": "테스트", "status": {"name": "진행 중"}})
        schema = Schema.from_issue(issue, self._mappings())
        assert schema.properties["issue"] == "PROJ-1"
        assert schema.properties["제목"] == "테스트"
        assert schema.properties["상태"] == "진행 중"

    def test_from_issue_missing_field_is_none(self):
        issue = Issue(key="PROJ-2", fields={})
        schema = Schema.from_issue(issue, self._mappings())
        assert schema.properties["제목"] is None
        assert schema.properties["상태"] is None

    def test_from_issue_all_mappings(self):
        """매핑 수만큼 properties가 생성되어야 함."""
        issue = Issue(key="PROJ-3", fields={"summary": "foo", "status": {"name": "Done"}})
        schema = Schema.from_issue(issue, self._mappings())
        assert len(schema.properties) == len(self._mappings())
