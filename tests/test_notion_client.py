from unittest.mock import MagicMock, patch, call
import pytest

from env import Env
from config import FieldMapping
from jira_client import Issue
from notion_client import NotionDatabase


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def env():
    return Env(
        jira_url="https://test.atlassian.net",
        jira_email="test@example.com",
        jira_api_token="jira-token",
        notion_api_key="notion-secret",
        notion_data_source_id="db-id-123",
    )

@pytest.fixture
def db(env):
    return NotionDatabase(env)

@pytest.fixture
def mappings():
    return [
        FieldMapping(jira_field="key", notion_property="issue", notion_type="title"),
        FieldMapping(jira_field="fields.summary", notion_property="제목", notion_type="rich_text"),
        FieldMapping(jira_field="fields.status.name", notion_property="상태", notion_type="status"),
    ]


# ──────────────────────────────────────────────
# _to_notion_property
# ──────────────────────────────────────────────

class TestToNotionProperty:

    def test_title(self):
        result = NotionDatabase._to_notion_property("PROJ-1", "title")
        assert result == {"title": [{"text": {"content": "PROJ-1"}}]}

    def test_title_none(self):
        result = NotionDatabase._to_notion_property(None, "title")
        assert result == {"title": [{"text": {"content": ""}}]}

    def test_rich_text(self):
        result = NotionDatabase._to_notion_property("내용", "rich_text")
        assert result == {"rich_text": [{"text": {"content": "내용"}}]}

    def test_rich_text_none(self):
        result = NotionDatabase._to_notion_property(None, "rich_text")
        assert result == {"rich_text": [{"text": {"content": ""}}]}

    def test_select_with_value(self):
        assert NotionDatabase._to_notion_property("High", "select") == {"select": {"name": "High"}}

    def test_select_none(self):
        assert NotionDatabase._to_notion_property(None, "select") == {"select": None}

    def test_status_with_value(self):
        assert NotionDatabase._to_notion_property("진행 중", "status") == {"status": {"name": "진행 중"}}

    def test_status_none(self):
        assert NotionDatabase._to_notion_property(None, "status") == {"status": None}

    def test_date_with_value(self):
        assert NotionDatabase._to_notion_property("2024-01-01", "date") == {"date": {"start": "2024-01-01"}}

    def test_date_none(self):
        assert NotionDatabase._to_notion_property(None, "date") == {"date": None}

    def test_url_with_value(self):
        assert NotionDatabase._to_notion_property("https://example.com", "url") == {"url": "https://example.com"}

    def test_url_none(self):
        assert NotionDatabase._to_notion_property(None, "url") == {"url": None}

    def test_unknown_type_fallback_to_rich_text(self):
        result = NotionDatabase._to_notion_property("값", "unknown")
        assert result == {"rich_text": [{"text": {"content": "값"}}]}


# ──────────────────────────────────────────────
# query
# ──────────────────────────────────────────────

class TestQuery:

    @patch("notion_client.requests.post")
    def test_success(self, mock_post, db):
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"results": []})
        result = db.query()
        assert result == {"results": []}

    @patch("notion_client.requests.post")
    def test_error_returns_empty(self, mock_post, db):
        mock_post.return_value = MagicMock(status_code=400, text="Bad Request")
        result = db.query()
        assert result == {}

    @patch("notion_client.requests.post")
    def test_none_values_excluded_from_body(self, mock_post, db):
        """None 값 필드는 request body에서 제외."""
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {})
        db.query({"filter": None, "page_size": 10})
        _, kwargs = mock_post.call_args
        assert "filter" not in kwargs["json"]
        assert kwargs["json"]["page_size"] == 10

    @patch("notion_client.requests.post")
    def test_filter_properties_sent_as_params(self, mock_post, db):
        """filter_properties는 URL 쿼리 파라미터로 전달."""
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {})
        db.query({"filter_properties": ["issue", "제목"], "page_size": 10})
        _, kwargs = mock_post.call_args
        assert "filter_properties" not in kwargs["json"]
        assert kwargs["params"] == {"filter_properties": ["issue", "제목"]}

    @patch("notion_client.requests.post")
    def test_no_filter_properties_no_params(self, mock_post, db):
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {})
        db.query({"page_size": 10})
        _, kwargs = mock_post.call_args
        assert kwargs["params"] is None


# ──────────────────────────────────────────────
# upsert
# ──────────────────────────────────────────────

class TestUpsert:

    def _existing_page(self, issue_key: str, page_id: str) -> dict:
        return {
            "id": page_id,
            "properties": {
                "issue": {"title": [{"text": {"content": issue_key}}]}
            },
        }

    @patch("notion_client.requests.post")
    def test_create_new_page(self, mock_post, db, mappings):
        """Notion에 없는 이슈 → POST로 신규 생성."""
        mock_post.side_effect = [
            MagicMock(status_code=200, json=lambda: {"results": []}),  # query
            MagicMock(status_code=200),                                  # create
        ]
        issues = [Issue(key="NEW-1", fields={"summary": "새 이슈", "status": {"name": "할 일"}})]
        db.upsert(issues, mappings)
        assert mock_post.call_count == 2

    @patch("notion_client.requests.patch")
    @patch("notion_client.requests.post")
    def test_update_existing_page(self, mock_post, mock_patch, db, mappings):
        """Notion에 이미 있는 이슈 → PATCH로 업데이트."""
        existing = self._existing_page("EXIST-1", "page-abc")
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"results": [existing]})
        mock_patch.return_value = MagicMock(status_code=200)

        issues = [Issue(key="EXIST-1", fields={"summary": "기존 이슈", "status": {"name": "진행 중"}})]
        db.upsert(issues, mappings)

        mock_patch.assert_called_once()
        patch_url = mock_patch.call_args[1]["url"]
        assert "page-abc" in patch_url

    @patch("notion_client.requests.post")
    def test_no_title_mapping_skips(self, mock_post, db):
        """title 매핑 없으면 upsert 수행하지 않음."""
        mappings_no_title = [
            FieldMapping(jira_field="fields.summary", notion_property="제목", notion_type="rich_text"),
        ]
        db.upsert([Issue(key="X-1", fields={})], mappings_no_title)
        mock_post.assert_not_called()

    @patch("notion_client.requests.post")
    def test_api_error_on_create(self, mock_post, db, mappings):
        """생성 API 실패 시 예외 없이 로그만 기록."""
        mock_post.side_effect = [
            MagicMock(status_code=200, json=lambda: {"results": []}),
            MagicMock(status_code=500, text="Internal Server Error"),
        ]
        issues = [Issue(key="ERR-1", fields={"summary": "오류", "status": {"name": "할 일"}})]
        db.upsert(issues, mappings)  # 예외 없이 종료되어야 함
