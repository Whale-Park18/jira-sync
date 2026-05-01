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


# ──────────────────────────────────────────────
# _lookup_pages
# ──────────────────────────────────────────────

class TestLookupPages:

    @patch("notion_client.requests.post")
    def test_filter_stripped_from_lookup(self, mock_post, db):
        """scan_mode="full"일 때 notion_query의 filter가 lookup 요청 body에 포함되지 않아야 함."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"results": [], "has_more": False},
        )
        notion_query = {"filter": {"property": "상태", "status": {"does_not_equal": "완료"}}, "page_size": 50}
        # scan_mode="full" 전달: filter 제거 동작 검증
        db._lookup_pages(notion_query, "issue", scan_mode="full")

        _, kwargs = mock_post.call_args
        assert "filter" not in kwargs["json"]
        assert kwargs["json"].get("page_size") == 50

    @patch("notion_client.requests.post")
    def test_title_property_auto_added_to_filter_properties(self, mock_post, db):
        """filter_properties에 title 컬럼이 없으면 자동으로 추가."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"results": [], "has_more": False},
        )
        notion_query = {"filter_properties": ["상태"]}
        db._lookup_pages(notion_query, "issue")

        _, kwargs = mock_post.call_args
        assert "issue" in kwargs["params"]["filter_properties"]

    @patch("notion_client.requests.post")
    def test_title_property_already_in_filter_properties_not_duplicated(self, mock_post, db):
        """filter_properties에 title 컬럼이 이미 있으면 중복 추가하지 않음."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"results": [], "has_more": False},
        )
        notion_query = {"filter_properties": ["issue", "상태"]}
        db._lookup_pages(notion_query, "issue")

        _, kwargs = mock_post.call_args
        assert kwargs["params"]["filter_properties"].count("issue") == 1

    @patch("notion_client.requests.post")
    def test_pagination_fetches_all_pages(self, mock_post, db):
        """has_more=True이면 next_cursor로 다음 페이지까지 모두 조회."""
        page1 = {"id": "p1", "properties": {}}
        page2 = {"id": "p2", "properties": {}}
        mock_post.side_effect = [
            MagicMock(status_code=200, json=lambda: {"results": [page1], "has_more": True, "next_cursor": "cur-1"}),
            MagicMock(status_code=200, json=lambda: {"results": [page2], "has_more": False}),
        ]

        pages = db._lookup_pages({}, "issue")

        assert len(pages) == 2
        assert mock_post.call_count == 2
        # 두 번째 요청에 start_cursor 포함 확인
        second_body = mock_post.call_args_list[1][1]["json"]
        assert second_body["start_cursor"] == "cur-1"

    @patch("notion_client.requests.post")
    def test_api_error_returns_empty_list(self, mock_post, db):
        """API 오류 시 빈 리스트 반환."""
        mock_post.return_value = MagicMock(status_code=500, text="Server Error")
        pages = db._lookup_pages({}, "issue")
        assert pages == []

    @patch("notion_client.requests.post")
    def test_upsert_finds_filtered_out_page(self, mock_post, db, mappings):
        """notion_query filter로 제외되는 페이지(완료 상태 등)도 중복 방지에 활용."""
        # 완료 상태 페이지가 lookup에서 반환됨 (filter 제거 덕분)
        existing = {
            "id": "page-done",
            "properties": {"issue": {"title": [{"text": {"content": "DONE-1"}}]}},
        }
        mock_post.side_effect = [
            MagicMock(status_code=200, json=lambda: {"results": [existing], "has_more": False}),
        ]
        # DONE-1이 lookup에 포함되므로 create가 아닌 patch 호출 예상
        with patch("notion_client.requests.patch") as mock_patch:
            mock_patch.return_value = MagicMock(status_code=200)
            notion_query = {"filter": {"property": "상태", "status": {"does_not_equal": "완료"}}}
            issues = [Issue(key="DONE-1", fields={"summary": "완료 이슈", "status": {"name": "완료"}})]
            # scan_mode="full"로 호출하여 filter 무시하고 전체 스캔 → 완료 페이지도 lookup에 포함
            db.upsert(issues, mappings, notion_query, scan_mode="full")

        mock_patch.assert_called_once()
        assert "page-done" in mock_patch.call_args[1]["url"]

    @patch("notion_client.requests.post")
    def test_filter_kept_when_scan_mode_filtered(self, mock_post, db):
        """scan_mode="filtered"(기본)에서는 filter가 요청 body에 그대로 포함되어야 함."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"results": [], "has_more": False},
        )
        notion_filter = {"property": "상태", "status": {"does_not_equal": "완료"}}
        notion_query = {"filter": notion_filter, "page_size": 50}
        # scan_mode="filtered" 명시 호출
        db._lookup_pages(notion_query, "issue", scan_mode="filtered")

        _, kwargs = mock_post.call_args
        # filter 유지 검증
        assert kwargs["json"].get("filter") == notion_filter
        assert kwargs["json"].get("page_size") == 50

    @patch("notion_client.requests.post")
    def test_filter_stripped_when_scan_mode_full(self, mock_post, db):
        """scan_mode="full"에서 filter가 body에서 제거되는지 검증."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"results": [], "has_more": False},
        )
        notion_query = {
            "filter": {"property": "상태", "status": {"does_not_equal": "완료"}},
            "sorts": [{"property": "생성일", "direction": "descending"}],
            "page_size": 30,
        }
        db._lookup_pages(notion_query, "issue", scan_mode="full")

        _, kwargs = mock_post.call_args
        # filter는 제거, 그 외 키(sorts/page_size)는 유지되어야 함
        assert "filter" not in kwargs["json"]
        assert kwargs["json"].get("sorts") == [{"property": "생성일", "direction": "descending"}]
        assert kwargs["json"].get("page_size") == 30

    @patch("notion_client.requests.post")
    def test_scan_mode_defaults_to_filtered(self, mock_post, db):
        """scan_mode 파라미터 미지정 호출 시 기본값("filtered")으로 filter 유지 동작."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"results": [], "has_more": False},
        )
        notion_filter = {"property": "상태", "status": {"does_not_equal": "완료"}}
        notion_query = {"filter": notion_filter}
        # scan_mode 파라미터 생략 호출
        db._lookup_pages(notion_query, "issue")

        _, kwargs = mock_post.call_args
        # 기본 "filtered"이므로 filter가 유지되어야 함
        assert kwargs["json"].get("filter") == notion_filter

    def test_upsert_passes_scan_mode_to_lookup(self, db, mappings):
        """upsert(scan_mode="full") 호출 시 _lookup_pages에 scan_mode="full"이 전달되는지 검증."""
        # _lookup_pages를 mock으로 대체하여 전달 인자 검증
        with patch.object(db, "_lookup_pages", return_value=[]) as mock_lookup:
            with patch("notion_client.requests.post") as mock_post:
                mock_post.return_value = MagicMock(status_code=200)
                issues = [Issue(key="X-1", fields={"summary": "s", "status": {"name": "할 일"}})]
                db.upsert(issues, mappings, notion_query={"filter": {"x": 1}}, scan_mode="full")

        mock_lookup.assert_called_once()
        # 키워드 인자로 scan_mode="full"이 전달되었는지 확인
        _, kwargs = mock_lookup.call_args
        assert kwargs.get("scan_mode") == "full"
