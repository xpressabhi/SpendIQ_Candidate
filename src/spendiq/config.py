"""Runtime configuration. Defaults to the free OpenCode Zen endpoint
(no API key required) — see .env.example for overrides."""

import os

from dotenv import load_dotenv

load_dotenv()

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://opencode.ai/zen/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "public")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-v4-flash-free")
MOCK = os.getenv("SPENDIQ_MOCK", "").lower() in ("1", "true", "yes")
