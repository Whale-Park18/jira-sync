import os
from dataclasses import dataclass
from dotenv import load_dotenv

@dataclass(frozen=True)
class Env:
    jira_url: str
    jira_email: str
    jira_api_token: str
    notion_api_key: str
    notion_data_source_id: str

def load_env() -> Env:
    """환경 변수 로드."""
    load_dotenv()

    # 필수 환경변수 누락 시 조기에 실패
    missing = [
        key for key in (
            "JIRA_URL",
            "JIRA_EMAIL",
            "JIRA_API_TOKEN",
            "NOTION_API_KEY",
            "NOTION_DATA_SOURCE_ID",
        )
        if not os.environ.get(key)
    ]
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    return Env(
        jira_url=os.environ["JIRA_URL"].rstrip("/"), # trailing slash 제거로 URL 중복 방지
        jira_email=os.environ["JIRA_EMAIL"],
        jira_api_token=os.environ["JIRA_API_TOKEN"],
        notion_api_key=os.environ["NOTION_API_KEY"],
        notion_data_source_id=os.environ["NOTION_DATA_SOURCE_ID"],
    )
