"""Settings configuration for the template agent.

This module provides centralized configuration management using Pydantic
BaseSettings for environment variable loading, validation, and default
value handling for the template agent service.
"""

import json
from functools import cached_property
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

from template_agent.src.core.exceptions.exceptions import AppException, AppExceptionCode
from template_agent.utils.pylogger import get_python_logger

# Initialize logger
logger = get_python_logger()

# Load environment variables with error handling
try:
    load_dotenv()
except Exception as e:
    # Log error but don't fail - environment variables might be set directly
    logger.warning(f"Could not load .env file: {e}")

_REQUIRED_SERVER_FIELDS = {"url"}
_MAX_MCP_SERVERS = 20


def _resolve_mcp_config_path(env_override: str) -> Path | None:
    """Return the resolved config path, or None when the fallback is missing."""
    if env_override:
        resolved = Path(env_override).resolve()
        if not resolved.is_file():
            raise AppException(
                f"MCP_SERVERS_CONFIG points to a missing file: "
                f"{env_override} (resolved: {resolved})",
                AppExceptionCode.CONFIGURATION_VALIDATION_ERROR,
            )
        return resolved

    fallback = (
        Path(__file__).resolve().parent.parent
        / "agent_config"
        / "mcp_servers.json"
    )
    return fallback if fallback.is_file() else None


def _validate_mcp_entry(name: str, cfg: Any) -> bool:
    """Validate a single MCP server entry. Returns True if valid."""
    if not isinstance(cfg, dict):
        logger.warning(f"MCP server '{name}': entry is not a dict — skipped")
        return False
    missing = _REQUIRED_SERVER_FIELDS - cfg.keys()
    if missing:
        raise AppException(
            f"MCP server '{name}' missing required fields: {missing}",
            AppExceptionCode.CONFIGURATION_VALIDATION_ERROR,
        )
    return True


class Settings(BaseSettings):
    """Configuration settings for the template agent.

    Uses Pydantic BaseSettings to load and validate configuration from
    environment variables. Provides default values for optional settings
    and validation for required ones.

    The settings are organized into logical groups:
    - Server Configuration: Host, port, SSL settings
    - Database Configuration: PostgreSQL connection parameters
    - Langfuse Configuration: Tracing and analytics settings
    - Google Configuration: Service account credentials
    - MCP Configuration: MCP server connection settings
    """

    # Server Configuration
    AGENT_HOST: str = Field(default="0.0.0.0", json_schema_extra={"env": "AGENT_HOST"})
    AGENT_PORT: int = Field(default=5002, json_schema_extra={"env": "AGENT_PORT"})
    AGENT_SSL_KEYFILE: Optional[str] = Field(
        default=None, json_schema_extra={"env": "AGENT_SSL_KEYFILE"}
    )
    AGENT_SSL_CERTFILE: Optional[str] = Field(
        default=None, json_schema_extra={"env": "AGENT_SSL_CERTFILE"}
    )
    PYTHON_LOG_LEVEL: str = Field(
        default="INFO", json_schema_extra={"env": "PYTHON_LOG_LEVEL"}
    )
    USE_INMEMORY_SAVER: bool = Field(
        default=False, json_schema_extra={"env": "USE_INMEMORY_SAVER"}
    )

    # Database Configuration
    POSTGRES_USER: str = Field(
        default="pgvector", json_schema_extra={"env": "POSTGRES_USER"}
    )
    POSTGRES_PASSWORD: str = Field(
        default="pgvector", json_schema_extra={"env": "POSTGRES_PASSWORD"}
    )
    POSTGRES_DB: str = Field(
        default="pgvector", json_schema_extra={"env": "POSTGRES_DB"}
    )
    POSTGRES_HOST: str = Field(
        default="pgvector", json_schema_extra={"env": "POSTGRES_HOST"}
    )
    POSTGRES_PORT: int = Field(default=5432, json_schema_extra={"env": "POSTGRES_PORT"})

    # Google Service Account Configuration
    GOOGLE_SERVICE_ACCOUNT_FILE: Optional[str] = Field(
        default=None, json_schema_extra={"env": "GOOGLE_SERVICE_ACCOUNT_FILE"}
    )

    # Langfuse Configuration
    LANGFUSE_PUBLIC_KEY: Optional[str] = Field(
        default=None, json_schema_extra={"env": "LANGFUSE_PUBLIC_KEY"}
    )
    LANGFUSE_SECRET_KEY: Optional[str] = Field(
        default=None, json_schema_extra={"env": "LANGFUSE_SECRET_KEY"}
    )
    LANGFUSE_BASE_URL: Optional[str] = Field(
        default=None, json_schema_extra={"env": "LANGFUSE_BASE_URL"}
    )
    LANGFUSE_TRACING_ENVIRONMENT: str = Field(
        default="development", json_schema_extra={"env": "LANGFUSE_TRACING_ENVIRONMENT"}
    )

    # Google Application Credentials
    GOOGLE_APPLICATION_CREDENTIALS_CONTENT: Optional[str] = Field(
        default=None,
        json_schema_extra={"env": "GOOGLE_APPLICATION_CREDENTIALS_CONTENT"},
    )

    # LLM Configuration (injected by AgentForge deployer from registry + vault)
    LLM_PROVIDER: str = Field(
        default="google",
        json_schema_extra={
            "env": "LLM_PROVIDER",
            "description": "LLM provider key: google, openai, anthropic, etc.",
        },
    )
    LLM_MODEL_ID: str = Field(
        default="gemini-3.1-pro-preview",
        json_schema_extra={
            "env": "LLM_MODEL_ID",
            "description": "Model identifier passed to the provider SDK.",
        },
    )
    LLM_API_KEY: Optional[str] = Field(
        default=None,
        json_schema_extra={
            "env": "LLM_API_KEY",
            "description": (
                "API key or service-account JSON injected by the deployer "
                "from Vault.  For Google, this is used as a fallback when "
                "GOOGLE_APPLICATION_CREDENTIALS_CONTENT is not set."
            ),
        },
    )

    # MCP Server Configuration (JSON-based — define N servers in one file)
    MCP_SERVERS_CONFIG: str = Field(
        default="",
        json_schema_extra={
            "env": "MCP_SERVERS_CONFIG",
            "description": (
                "Path to an mcp_servers.json file that declares all MCP "
                "servers.  Falls back to agent_config/mcp_servers.json "
                "when empty."
            ),
        },
    )
    MCP_CONNECTION_TIMEOUT: int = Field(
        default=30,
        json_schema_extra={"env": "MCP_CONNECTION_TIMEOUT"},
    )

    GATEWAY_INTERNAL_URL: str = Field(
        default="",
        json_schema_extra={"env": "GATEWAY_INTERNAL_URL"},
    )

    # Request Logging Configuration
    REQUEST_LOGGING_ENABLED: bool = Field(
        default=True,
        json_schema_extra={
            "env": "REQUEST_LOGGING_ENABLED",
            "description": "Enable request/response logging",
        },
    )
    REQUEST_LOG_HEADERS: bool = Field(
        default=True,
        json_schema_extra={
            "env": "REQUEST_LOG_HEADERS",
            "description": "Include headers in request/response logs",
        },
    )
    REQUEST_LOG_BODY: bool = Field(
        default=False,
        json_schema_extra={
            "env": "REQUEST_LOG_BODY",
            "description": "Include body content in request/response logs",
        },
    )
    REQUEST_LOG_BODY_MAX_SIZE: int = Field(
        default=10240,
        json_schema_extra={
            "env": "REQUEST_LOG_BODY_MAX_SIZE",
            "description": "Maximum body size in bytes to log (0 for unlimited)",
        },
    )

    @cached_property
    def mcp_servers(self) -> dict[str, dict[str, Any]]:
        """Load and cache MCP server definitions from the JSON config file.

        Reads ``mcp_servers.json`` once, validates each entry, and returns
        only servers where ``"enabled"`` is explicitly ``true``.  Servers
        without an ``enabled`` field default to **disabled** (opt-in).

        Falls back to the baked-in ``agent_config/mcp_servers.json`` only
        when ``MCP_SERVERS_CONFIG`` is empty.  If ``MCP_SERVERS_CONFIG``
        is set but the file does not exist, an error is raised to avoid
        silent misconfiguration.
        """
        config_path = _resolve_mcp_config_path(self.MCP_SERVERS_CONFIG)
        if config_path is None:
            logger.warning("MCP servers config not found — no MCP tools will load")
            return {}

        raw = config_path.read_text()
        if len(raw) > 1_048_576:
            raise AppException(
                "MCP config file exceeds 1 MB size limit",
                AppExceptionCode.CONFIGURATION_VALIDATION_ERROR,
            )

        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, OSError) as exc:
            raise AppException(
                f"Failed to parse MCP config {config_path}: {exc}",
                AppExceptionCode.CONFIGURATION_VALIDATION_ERROR,
            ) from exc

        all_servers = data.get("mcpServers") or {}
        if not isinstance(all_servers, dict):
            raise AppException(
                f"'mcpServers' must be a JSON object, got {type(all_servers).__name__}",
                AppExceptionCode.CONFIGURATION_VALIDATION_ERROR,
            )

        if len(all_servers) > _MAX_MCP_SERVERS:
            raise AppException(
                f"MCP config declares {len(all_servers)} servers "
                f"(max {_MAX_MCP_SERVERS})",
                AppExceptionCode.CONFIGURATION_VALIDATION_ERROR,
            )

        enabled: dict[str, dict[str, Any]] = {}
        for name, cfg in all_servers.items():
            if not _validate_mcp_entry(name, cfg):
                continue
            if cfg.get("enabled", False):
                enabled[name] = cfg

        logger.info(
            f"MCP config loaded: {len(enabled)}/{len(all_servers)} servers "
            f"enabled from {config_path}"
        )
        return enabled

    @property
    def database_uri(self) -> str:
        """Generate database URI from individual components.

        Constructs a PostgreSQL connection URI using the configured
        database settings including user, password, host, port, and
        database name.

        Returns:
            The complete PostgreSQL database URI string.
        """
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"


def validate_config(settings: Settings) -> None:
    """Validate configuration settings.

    Performs comprehensive validation to ensure required settings are
    present and values are within acceptable ranges. This function
    validates port ranges and log levels.

    Args:
        settings: Settings instance to validate.

    Raises:
        ValueError: If required configuration is missing or invalid.
    """
    # Validate port range
    if not (1024 <= settings.AGENT_PORT <= 65535):
        logger.error(
            f"AGENT_PORT must be between 1024 and 65535, got {settings.AGENT_PORT}"
        )
        raise AppException(
            f"AGENT_PORT must be between 1024 and 65535, got {settings.AGENT_PORT}",
            AppExceptionCode.CONFIGURATION_VALIDATION_ERROR,
        )

    # Validate log level
    valid_log_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    if settings.PYTHON_LOG_LEVEL.upper() not in valid_log_levels:
        logger.error(
            f"PYTHON_LOG_LEVEL must be one of {valid_log_levels}, got {settings.PYTHON_LOG_LEVEL}"
        )
        raise AppException(
            f"PYTHON_LOG_LEVEL must be one of {valid_log_levels}, got {settings.PYTHON_LOG_LEVEL}",
            AppExceptionCode.CONFIGURATION_VALIDATION_ERROR,
        )


# Create settings instance without validation (validation happens in main.py)
settings = Settings()
