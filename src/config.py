from pydantic_settings import BaseSettings

NEBIUS_API_KEY_ENV = "NEBIUS_API_KEY"
NEBIUS_API_BASE = "https://api.studio.nebius.ai/v1/"

PLANNER_MODEL = "meta-llama/Meta-Llama-3.1-8B-Instruct"
WORKER_MODEL = "deepseek-ai/DeepSeek-V3"

# Tuneable thresholds
MAX_FILE_SIZE_BYTES = 150 * 1024       # 150 KB
MAX_CHARS_PER_FILE = 10_000            # chars sent to LLM per file
MAX_FILES_INCLUDED = 30
LARGE_REPO_TOKEN_THRESHOLD = 50_000   # tokens; above → map/reduce
TOKEN_ESTIMATE_RATIO = 4               # chars per token (conservative)
LLM_TIMEOUT_SECONDS = 60
GITHUB_TIMEOUT_SECONDS = 15
MAX_SUBTREE_EXPANSIONS = 12
MAX_TREE_DEPTH = 4


class Settings(BaseSettings):
    nebius_api_key: str
    github_token: str = ""  # optional — unauthenticated GitHub API has 60 req/hour limit

    model_config = {"env_file": ".env", "extra": "ignore"}


# Singleton — loaded once at import time; crashes if vars are missing
settings = Settings()  # type: ignore[call-arg]
