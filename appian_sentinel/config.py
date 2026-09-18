from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    litellm_base_url: str = "http://localhost:4000"
    litellm_api_key: str = ""

    sentinel_primary_model: str = "bedrock.anthropic.claude-opus-4-8"
    sentinel_fast_model: str = "bedrock.anthropic.claude-sonnet-5"

    sentinel_host: str = "0.0.0.0"
    sentinel_port: int = 8000
    sentinel_workspace: Path = Path("./workspace")

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
