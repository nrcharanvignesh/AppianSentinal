from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings

from appian_sentinel.knowledge.genai_catalog import (
    GenAIConfigDefaults,
    get_config_defaults,
)

_FALLBACK_BASE_URL = "http://localhost:4000"
_FALLBACK_PRIMARY_MODEL = "bedrock.anthropic.claude-opus-4-8"
_FALLBACK_FAST_MODEL = "bedrock.anthropic.claude-sonnet-5"
_CATALOG_DEFAULTS = get_config_defaults(
    _FALLBACK_BASE_URL,
    _FALLBACK_PRIMARY_MODEL,
    _FALLBACK_FAST_MODEL,
) or GenAIConfigDefaults(
    base_url=_FALLBACK_BASE_URL,
    primary_model=_FALLBACK_PRIMARY_MODEL,
    fast_model=_FALLBACK_FAST_MODEL,
)


class Settings(BaseSettings):
    litellm_base_url: str = _CATALOG_DEFAULTS.base_url
    litellm_api_key: str = ""
    llm_protocol: Literal["auto", "openai", "anthropic"] = "auto"

    sentinel_primary_model: str = _CATALOG_DEFAULTS.primary_model
    sentinel_fast_model: str = _CATALOG_DEFAULTS.fast_model

    sentinel_host: str = "0.0.0.0"
    sentinel_port: int = 8000
    sentinel_workspace: Path = Field(
        default=Path("./workspace"),
        validation_alias=AliasChoices("SENTINEL_WORKSPACE_DIR", "sentinel_workspace"),
    )

    sentinel_max_agent_iterations: int = 20
    sentinel_max_tokens: int = 64000

    # --- Azure DevOps (work-item source) ---
    # ado_source: "pat" (self-contained REST) or "mcp" (desktop MCP bridge)
    ado_source: str = "pat"
    ado_org: str = ""
    ado_project: str = ""
    ado_pat: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
