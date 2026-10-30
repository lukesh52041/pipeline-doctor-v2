import os
from dataclasses import dataclass


def _init_env():
    for base in [os.getcwd(), os.path.dirname(os.path.dirname(os.path.dirname(__file__)))]:
        env_file = os.path.join(base, ".env")
        if os.path.isfile(env_file):
            try:
                with open(env_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        k, _, v = line.partition("=")
                        k = k.strip()
                        v = v.strip().strip("'\"")
                        if k and k not in os.environ:
                            os.environ[k] = v
                break
            except Exception:  # noqa: BLE001
                pass


_init_env()


@dataclass(frozen=True)
class Settings:
    db_path: str
    anthropic_api_key: str
    llm_model: str
    api_keys: dict
    github_token: str
    webhook_secret: str
    max_log_bytes: int
    tinyfish_api_key: str
    tinyfish_location: str
    tinyfish_language: str
    tinyfish_enabled: bool


def get_settings() -> Settings:
    keys: dict[str, str] = {}
    for part in (p.strip() for p in os.getenv("API_KEYS", "").split(",")):
        if not part:
            continue
        key, _, role = part.partition(":")
        keys[key] = role or "developer"
    tinyfish_enabled_raw = os.getenv("TINYFISH_ENABLED", "true").strip().lower()
    tinyfish_enabled = tinyfish_enabled_raw in ("true", "1", "yes")
    return Settings(
        db_path=os.getenv("DB_PATH", "data/pipelinedoctor.db"),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        llm_model=os.getenv("LLM_MODEL", "claude-sonnet-4-6"),
        api_keys=keys,
        github_token=os.getenv("GITHUB_TOKEN", ""),
        webhook_secret=os.getenv("GITHUB_WEBHOOK_SECRET", ""),
        max_log_bytes=int(os.getenv("MAX_LOG_BYTES", "2000000")),
        tinyfish_api_key=os.getenv("TINYFISH_API_KEY", ""),
        tinyfish_location=os.getenv("TINYFISH_LOCATION", "US"),
        tinyfish_language=os.getenv("TINYFISH_LANGUAGE", "en"),
        tinyfish_enabled=tinyfish_enabled,
    )
