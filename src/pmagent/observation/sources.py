from __future__ import annotations

import os
from pathlib import Path

from pmagent.web_search import load_dotenv


def load_runtime_env(repo_root: Path) -> dict[str, str]:
    dotenv_path = repo_root / ".env"
    load_dotenv(dotenv_path)
    keys = (
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "WEEKLY_AI_API_KEY",
        "WEEKLY_AI_BASE_URL",
        "PMAGENT_AGENT_BACKEND",
    )
    return {key: os.environ.get(key, "") for key in keys}
