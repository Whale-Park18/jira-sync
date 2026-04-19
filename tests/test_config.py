import textwrap
import pytest
from config import (
    _validate_notion_query,
    _validate_mappings,
    load_config,
)


# ──────────────────────────────────────────────
# _validate_notion_query
# ──────────────────────────────────────────────

class TestValidateNotionQuery:

    def test_valid_full(self):
        """모든 필드가 정상인 경우 예외 없음."""
        _validate_notion_query({
            "filter": {"property": "상태", "status": {"does_not_equal": "완료"}},
            "sorts": [{"property": "생성일", "direction": "ascending"}],
            "page_size": 50,
            "filter_properties": ["issue", "제목"],
        })

    def test_valid_empty(self):
        """빈 dict는 유효."""
        _validate_notion_query({})

    def test_valid_none_fields(self):
        """값이 None인 필드는 무시."""
        _validate_notion_query({"filter": None, "sorts": None, "page_size": None})

    def test_invalid_type(self):
        """dict가 아니면 ValueError."""
        with pytest.raises(ValueError, match="dict 타입"):
            _validate_notion_query("not a dict")

    def test_filter_not_dict(self):
        with pytest.raises(ValueError, match="filter는 dict"):
            _validate_notion_query({"filter": "invalid"})

    def test_sorts_not_list(self):
        with pytest.raises(ValueError, match="sorts는 list"):
            _validate_notion_query({"sorts": "ascending"})

    def test_sorts_item_not_dict(self):
        with pytest.raises(ValueError, match=r"sorts\[0\]는 dict"):
            _validate_notion_query({"sorts": ["ascending"]})

    def test_sorts_missing_property(self):
        with pytest.raises(ValueError, match="property가 없습니다"):
            _validate_notion_query({"sorts": [{"direction": "ascending"}]})

    def test_sorts_missing_direction(self):
        with pytest.raises(ValueError, match="direction이 없습니다"):
            _validate_notion_query({"sorts": [{"property": "생성일"}]})

    def test_sorts_invalid_direction(self):
        with pytest.raises(ValueError, match="direction은"):
            _validate_notion_query({"sorts": [{"property": "생성일", "direction": "asc"}]})

    def test_page_size_zero(self):
        with pytest.raises(ValueError, match="1~100"):
            _validate_notion_query({"page_size": 0})

    def test_page_size_over_100(self):
        with pytest.raises(ValueError, match="1~100"):
            _validate_notion_query({"page_size": 101})

    def test_page_size_not_int(self):
        with pytest.raises(ValueError, match="1~100"):
            _validate_notion_query({"page_size": "100"})

    def test_filter_properties_not_list(self):
        with pytest.raises(ValueError, match="filter_properties는 list"):
            _validate_notion_query({"filter_properties": "issue"})

    def test_filter_properties_item_not_str(self):
        with pytest.raises(ValueError, match=r"filter_properties\[0\]는 문자열"):
            _validate_notion_query({"filter_properties": [123]})


# ──────────────────────────────────────────────
# _validate_mappings
# ──────────────────────────────────────────────

class TestValidateMappings:

    def _base_mapping(self, notion_type="rich_text"):
        return {"jira_field": "fields.summary", "notion_property": "제목", "notion_type": notion_type}

    def _title_mapping(self):
        return {"jira_field": "key", "notion_property": "issue", "notion_type": "title"}

    def test_valid(self):
        _validate_mappings([self._title_mapping(), self._base_mapping()])

    def test_no_title(self):
        with pytest.raises(ValueError, match="title.*하나 이상"):
            _validate_mappings([self._base_mapping()])

    def test_multiple_titles(self):
        with pytest.raises(ValueError, match="title.*하나여야"):
            _validate_mappings([self._title_mapping(), self._title_mapping()])

    def test_missing_jira_field(self):
        m = self._title_mapping()
        m2 = {"notion_property": "제목", "notion_type": "rich_text"}
        with pytest.raises(ValueError, match="jira_field가 누락"):
            _validate_mappings([m, m2])

    def test_missing_notion_property(self):
        m = self._title_mapping()
        m2 = {"jira_field": "fields.summary", "notion_type": "rich_text"}
        with pytest.raises(ValueError, match="notion_property가 누락"):
            _validate_mappings([m, m2])

    def test_invalid_notion_type(self):
        m = self._title_mapping()
        m2 = {"jira_field": "fields.summary", "notion_property": "제목", "notion_type": "number"}
        with pytest.raises(ValueError, match="notion_type은"):
            _validate_mappings([m, m2])


# ──────────────────────────────────────────────
# load_config
# ──────────────────────────────────────────────

class TestLoadConfig:

    def _write_yaml(self, tmp_path, content: str):
        """임시 YAML 파일 작성 후 경로 반환."""
        path = tmp_path / "sync_config.yaml"
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        return str(path)

    def test_valid_config(self, tmp_path):
        path = self._write_yaml(tmp_path, """
            jira_query:
              jql: "project = TEST"
              maxResults: 50
              fields:
                - summary
            notion_query:
              page_size: 10
            mappings:
              - jira_field: key
                notion_property: issue
                notion_type: title
              - jira_field: fields.summary
                notion_property: 제목
                notion_type: rich_text
        """)
        config = load_config(path)
        assert config.query.jql == "project = TEST"
        assert config.query.max_results == 50
        assert config.query.fields == ["summary"]
        assert config.notion_query == {"page_size": 10}
        assert len(config.mappings) == 2

    def test_missing_jira_query(self, tmp_path):
        path = self._write_yaml(tmp_path, """
            mappings:
              - jira_field: key
                notion_property: issue
                notion_type: title
        """)
        with pytest.raises(KeyError):
            load_config(path)

    def test_invalid_notion_query_raises(self, tmp_path):
        path = self._write_yaml(tmp_path, """
            jira_query:
              jql: "project = TEST"
              maxResults: 10
              fields: [summary]
            notion_query:
              page_size: 200
            mappings:
              - jira_field: key
                notion_property: issue
                notion_type: title
        """)
        with pytest.raises(ValueError, match="1~100"):
            load_config(path)
