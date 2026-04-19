# jira-sync

Jira 이슈를 Notion 데이터베이스에 단방향(Jira → Notion) 동기화하는 Python CLI 도구.

Jira를 source of truth로 유지하면서 Notion에서 이슈 현황을 시각적으로 확인할 수 있습니다.

---

## 아키텍처

### 디렉토리 구조

```
jira-sync/
├── sync.py                 # CLI 진입점
├── sync_config.yaml        # JQL 쿼리, Notion 쿼리, 필드 매핑 설정
├── requirements.txt
├── conftest.py             # pytest용 src/ 경로 등록
│
├── src/
│   ├── api_urls.py         # Jira · Notion REST API URL 상수
│   ├── config.py           # sync_config.yaml 로드 → SyncConfig
│   ├── env.py              # .env 로드 → Env
│   ├── jira_client.py      # Jira REST API 래퍼
│   ├── notion_client.py    # Notion API 래퍼 (NotionDatabase)
│   └── notion_schema.py    # Jira 필드 → Notion 프로퍼티 변환 (Schema)
│
├── tests/
│   ├── test_config.py
│   ├── test_jira_client.py
│   ├── test_notion_client.py
│   └── test_notion_schema.py
│
├── .env                    # 환경변수 (API 키 등)
└── .env.example            # 환경변수 템플릿
```

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

### 시퀀스 다이어그램

```mermaid
sequenceDiagram
    actor User
    participant sync as sync.py
    participant env as env.py
    participant config as config.py
    participant jira as jira_client.py
    participant JiraAPI as Jira REST API
    participant notion as notion_client.py
    participant NotionAPI as Notion API

    User->>sync: python sync.py [--dry-run]
    sync->>env: load_env()
    env-->>sync: Env
    sync->>config: load_config()
    config-->>sync: SyncConfig (jira_query + notion_query + mappings)

    sync->>jira: issue_search()
    jira->>JiraAPI: POST /rest/api/3/search/jql
    JiraAPI-->>jira: issues[]
    jira-->>sync: List[Issue]

    alt dry-run
        sync->>User: 동기화 없이 종료
    else 실제 동기화
        sync->>notion: upsert(issues, mappings, notion_query)
        notion->>NotionAPI: POST /data_sources/{id}/query
        NotionAPI-->>notion: 기존 페이지 목록

        loop 이슈별 처리
            notion->>notion: Schema.from_issue(issue, mappings)

            alt 기존 페이지 있음
                notion->>NotionAPI: PATCH /pages/{id}
                NotionAPI-->>notion: 200 OK
            else 신규 이슈
                notion->>NotionAPI: POST /pages
                NotionAPI-->>notion: 200 OK
            end
        end

        notion-->>sync: 완료
        sync->>User: 동기화 완료 로그
    end
```

### 동기화 전략

**Upsert by title** — `notion_type: title`로 지정된 매핑 항목을 기준으로 Notion DB에서 기존 페이지를 조회한 뒤, 있으면 update, 없으면 create합니다. 삭제는 수행하지 않습니다.

### 기본 동기화 필드 (sync_config.yaml)

| Jira 필드 | Notion 프로퍼티 | 타입 |
|---|---|---|
| `key` | `issue` | title |
| `fields.summary` | `제목` | rich_text |
| `fields.creator.displayName` | `담당자` | rich_text |
| `fields.priority.name` | `우선 순위` | select |
| `fields.status.name` | `상태` | status |
| `fields.created` | `생성일` | date |
| `fields.duedate` | `마감일` | date |

---

## 설치

```bash
pip install -r requirements.txt
```

## 환경변수 설정

`.env.example`을 복사해 `.env`를 작성합니다.

```bash
cp .env.example .env
```

```env
JIRA_URL=https://your-domain.atlassian.net
JIRA_EMAIL=your-email@example.com
JIRA_API_TOKEN=your-jira-api-token

NOTION_API_KEY=secret_your-notion-integration-key
NOTION_DATA_SOURCE_ID=your-notion-data-source-id
```

## 동기화 설정

`sync_config.example.yaml`을 복사해 `sync_config.yaml`을 작성합니다.

```bash
cp sync_config.example.yaml sync_config.yaml
```

이후 `jira_query.jql`, `notion_query`, `mappings`를 프로젝트에 맞게 수정합니다.

## 사용법

```bash
# 기본 실행
python sync.py

# 다른 설정 파일 사용
python sync.py --config other_config.yaml

# 실제 반영 없이 결과만 확인
python sync.py --dry-run
```

## 테스트

```bash
python -m pytest tests/ -v
```
