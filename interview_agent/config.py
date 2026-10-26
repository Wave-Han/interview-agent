# interview_agent/config.py
import os
from dataclasses import dataclass
from dotenv import load_dotenv

@dataclass
class Config:
    base_url: str
    api_key: str
    model: str
    db_path: str
    redis_url: str | None = None
    embedding_model: str = "embedding-3"

def load_config(env_path: str = ".env") -> Config:
    """Load LLM and storage config from env file plus process env."""
    load_dotenv(env_path)
    return Config(
        base_url=os.environ["LLM_BASE_URL"],
        api_key=os.environ["LLM_API_KEY"],
        model=os.environ.get("LLM_MODEL", "glm-4-flash"),
        db_path=os.environ.get("DB_PATH", "interview.db"),
        redis_url=os.environ.get("REDIS_URL"),
        embedding_model=os.environ.get("EMBEDDING_MODEL", "embedding-3"),
    )
