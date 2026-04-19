# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## ai request

- 코드 작성 시, 주석 추가

## Commands

```bash
# 의존성 설치
pip install -r requirements.txt

# 실제 동기화 실행
python sync.py

# 다른 설정 파일 사용
python sync.py --config other_config.yaml

# Notion에 반영하지 않고 결과만 확인
python sync.py --dry-run

# 테스트 실행
python -m pytest tests/ -v
```

## 아키텍처

**Jira → Notion 단방향 동기화 CLI.** `sync_config.yaml` 하나로 JQL 쿼리, Notion 쿼리, 필드 매핑을 정의하며, 코드 수정 없이 커스터마이징 가능.

### 데이터 흐름

```
sync.py
  └─ load_env()                              # .env 로드
  └─ load_config()                           # sync_config.yaml 로드 · 유효성 검사
  └─ JiraClient.issue_search()               # JQL로 이슈 조회
  └─ NotionDatabase.upsert(issues, mappings) # Notion DB 조회 후 upsert
       └─ NotionDatabase.query()             # 기존 페이지 조회 (notion_query 적용)
       └─ Schema.from_issue(issue, mappings) # Jira 필드 → Notion properties 변환
       └─ PATCH /pages/{id}                  # 기존 페이지 업데이트
       └─ POST /pages                        # 신규 페이지 생성
```

### 핵심 설계 결정

**YAML 기반 매핑** — `sync_config.yaml`의 `mappings` 배열이 변환 규칙 전체를 정의. `notion_schema.py`의 `Schema.from_issue()`가 이를 읽어 범용 변환을 수행하므로, 필드 추가/변경은 YAML만 편집하면 됨.

**Upsert 키** — `notion_type: title`인 매핑 항목이 Notion 페이지의 중복 판별 기준. DB에서 해당 값으로 조회 후 있으면 update, 없으면 create.

**중첩 필드 접근** — `jira_field`에 점 표기법 사용 가능 (`fields.status.name`, `fields.priority.name`). `key`는 Jira issue 최상위 필드로 특수 처리, 나머지는 `fields.*` 경로.

**지원 Notion 프로퍼티 타입** — `title`, `rich_text`, `select`, `status`, `date`, `url`. 새 타입 추가 시 `src/notion_client.py`의 `NotionDatabase._to_notion_property()` 수정 필요.

**notion_query 전송 방식** — `filter`, `sorts`, `page_size`는 request body로 전송. `filter_properties`만 URL 쿼리 파라미터로 분리 전송. `None` 값 필드는 자동 제외.

### 환경 변수 (.env)

| 변수 | 설명 |
|---|---|
| `JIRA_URL` | Atlassian 도메인 (예: `https://xxx.atlassian.net`) |
| `JIRA_EMAIL` | Jira 계정 이메일 |
| `JIRA_API_TOKEN` | Jira API 토큰 |
| `NOTION_API_KEY` | Notion integration secret |
| `NOTION_DATA_SOURCE_ID` | 동기화 대상 Notion Data Source ID |

### 동기화 설정 (sync_config.yaml)

```yaml
jira_query:
  jql: "..."          # Jira 이슈 필터 조건
  maxResults: 100
  fields:             # 조회할 Jira 필드 목록
    - summary

notion_query:
  filter:             # Notion DB 필터 (네이티브 YAML)
    property: 상태
    status:
      does_not_equal: 완료
  sorts:              # 정렬
    - property: 생성일
      direction: descending
  page_size: 100      # 최대 100
  filter_properties:  # 응답에 포함할 컬럼 (URL 쿼리 파라미터로 전달)
    - issue

mappings:
  - jira_field: key              # 점 표기법 지원 (key, fields.summary, fields.status.name 등)
    notion_property: issue       # Notion DB 컬럼명
    notion_type: title           # title | rich_text | select | status | date | url
```
