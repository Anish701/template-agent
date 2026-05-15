"""Agent implementation for the template agent system.

This module provides the core agent functionality using the deepagents library,
including initialization, configuration, and agent creation with MCP tools,
skills, subagents, and memory.
"""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import yaml
from deepagents import SubAgent, create_deep_agent
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from template_agent.src.core.backend import get_backend
from template_agent.src.core.exceptions.exceptions import AppException, AppExceptionCode
from template_agent.src.core.prompt import get_system_prompt
from template_agent.src.core.storage import get_global_checkpoint, get_global_store
from template_agent.src.core.token_auth import SSOTokenAuth
from template_agent.src.core.token_manager import TokenManager
from template_agent.src.settings import settings
from template_agent.utils.pylogger import get_python_logger

logger = get_python_logger(log_level=settings.PYTHON_LOG_LEVEL)

_AUTH_RETRY_HTTP_STATUSES: tuple[int, ...] = (401, 403)


def _walk_exception_chain(exc: BaseException) -> list[BaseException]:
    """Flatten an exception and its ``__cause__`` / ``__context__`` / group children."""
    chain: list[BaseException] = []
    seen: set[int] = set()

    def walk(err: BaseException | None) -> None:
        if err is None:
            return
        ident = id(err)
        if ident in seen:
            return
        seen.add(ident)
        chain.append(err)
        if err.__cause__ is not None:
            walk(err.__cause__)
        if err.__context__ is not None and err.__context__ is not err.__cause__:
            walk(err.__context__)
        if isinstance(err, BaseExceptionGroup):
            for sub in err.exceptions:
                walk(sub)

    walk(exc)
    return chain


def _first_auth_retry_status(exc: BaseException) -> int | None:
    """Return the first 401/403 status found anywhere in the exception chain."""
    for e in _walk_exception_chain(exc):
        if isinstance(e, httpx.HTTPStatusError):
            code = e.response.status_code
            if code in _AUTH_RETRY_HTTP_STATUSES:
                return code
    return None


def _is_unauthorized(exc: BaseException) -> bool:
    return _first_auth_retry_status(exc) is not None


def _wrap_mcp_tool_for_sso_retry(
    tool: BaseTool,
    token_manager: TokenManager,
    reload_tools: Callable[[], Awaitable[list[BaseTool]]],
) -> BaseTool:
    """Wrap an MCP tool so that 401/403 triggers token refresh + tool reload."""
    original_ainvoke = tool.ainvoke

    async def ainvoke_with_retry(
        input: Any,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> Any:
        try:
            return await original_ainvoke(input, config=config, **kwargs)
        except BaseException as e:
            if not _is_unauthorized(e):
                raise
            status = _first_auth_retry_status(e)
            logger.warning(
                "MCP tool HTTP %s on %r; refreshing SSO token and reloading tools",
                status,
                tool.name,
            )
            await token_manager.force_refresh()
            fresh_tools = await reload_tools()
            replacement = next((t for t in fresh_tools if t.name == tool.name), None)
            if replacement is None:
                raise
            wrapped = _wrap_mcp_tool_for_sso_retry(
                replacement, token_manager, reload_tools
            )
            return await wrapped.ainvoke(input, config=config, **kwargs)

    object.__setattr__(tool, "ainvoke", ainvoke_with_retry)
    return tool

CONFIG_DIR = Path(__file__).parent.parent.parent / "agent_config"


def _parse_agent_frontmatter(path: Path) -> dict[str, Any]:
    r"""Parse a markdown agent file with YAML frontmatter.

    Expects the format: ``--- \\n <yaml> \\n --- \\n <markdown body>``.
    The markdown body is returned under the ``"body"`` key as the
    subagent's system prompt.

    Args:
        path: Path to the ``.md`` agent definition file.

    Returns:
        A dict of frontmatter fields plus ``body`` (the markdown body).
    """
    content = path.read_text()
    if not content.startswith("---"):
        return {"body": content.strip()}

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {"body": content.strip()}

    frontmatter: dict[str, Any] = yaml.safe_load(parts[1]) or {}
    frontmatter["body"] = parts[2].strip()
    return frontmatter


@asynccontextmanager
async def get_template_agent(
    token_manager: TokenManager | None = None,
):
    """Get a fully initialized deep agent with MCP tools, skills, subagents, and memory.

    This function creates and configures a deep agent using the deepagents library
    with the necessary tools from MCP, skills, subagents, and memory. It uses an
    async context manager to ensure proper resource cleanup.

    Args:
        token_manager: Holds the SSO token and refreshes it against the gateway.

    Yields:
        The initialized deep agent instance.

    Raises:
        Exception: If there are issues with database connections or agent setup.
    """
    # Pre-flight: ensure token is fresh before connecting to MCP servers
    if token_manager:
        await token_manager.get_valid_token()

    sso_token = token_manager.current_token if token_manager else None

    # Initialize MCP client and get tools from all enabled servers
    tools: list[BaseTool] = []

    mcp_defs = settings.mcp_servers
    logger.info(
        f"MCP connection timeout: {settings.MCP_CONNECTION_TIMEOUT}s | "
        f"SSO authentication: {'Yes' if sso_token else 'No'} | "
        f"Enabled servers: {list(mcp_defs.keys()) or '(none)'}"
    )

    _MAX_CONCURRENT_MCP = 5

    def _build_server_config(
        name: str,
        defn: dict[str, Any],
        default_token: str | None,
    ) -> dict:
        url = defn["url"]
        if isinstance(url, str) and url and not url.endswith("/"):
            url = f"{url}/"
        transport = defn.get("transport", "streamable_http")
        ssl_verify = defn.get("ssl_verify", False)

        wants_auth = defn.get("auth", True)
        token = default_token if wants_auth else None

        auth = (
            SSOTokenAuth(token, gateway_url=settings.GATEWAY_INTERNAL_URL)
            if token
            else None
        )

        config: dict = {
            "url": url,
            "transport": transport,
        }
        def _make_client(_auth=auth, _verify=ssl_verify, **kwargs):
            kwargs.pop("auth", None)
            kwargs.pop("verify", None)
            kwargs.pop("follow_redirects", None)
            return httpx.AsyncClient(auth=_auth, verify=_verify, follow_redirects=True, **kwargs)  # nosec B501

        config["httpx_client_factory"] = _make_client
        logger.info(
            f"MCP server '{name}' configured: {url} "
            f"(transport={transport}, ssl_verify={ssl_verify}, "
            f"auth={'sso' if token else 'none'})"
        )
        return config

    def _build_all_server_configs() -> dict[str, dict]:
        current = token_manager.current_token if token_manager else None
        return {
            name: _build_server_config(name, defn, current)
            for name, defn in mcp_defs.items()
        }

    server_configs = _build_all_server_configs()

    if server_configs:
        semaphore = asyncio.Semaphore(_MAX_CONCURRENT_MCP)

        async def _try_single_server(srv_name: str, srv_cfg: dict) -> list:
            """Connect to one MCP server; return tools or empty on failure."""
            async with semaphore:
                try:
                    client = MultiServerMCPClient({srv_name: srv_cfg})
                    srv_tools = await asyncio.wait_for(
                        client.get_tools(),
                        timeout=settings.MCP_CONNECTION_TIMEOUT,
                    )
                    logger.info(
                        f"MCP server '{srv_name}': loaded {len(srv_tools)} tools"
                    )
                    return srv_tools
                except asyncio.TimeoutError:
                    logger.error(
                        f"MCP server '{srv_name}': timeout after "
                        f"{settings.MCP_CONNECTION_TIMEOUT}s"
                    )
                except Exception:
                    logger.error(
                        f"MCP server '{srv_name}': connection failed",
                        exc_info=True,
                    )
            return []

        results = await asyncio.gather(
            *(
                _try_single_server(name, cfg)
                for name, cfg in server_configs.items()
            )
        )

        seen_tool_names: set[str] = set()
        for server_tools in results:
            for tool in server_tools:
                tname = getattr(tool, "name", None)
                if tname and tname in seen_tool_names:
                    logger.warning(
                        f"Duplicate MCP tool '{tname}' — "
                        f"keeping first occurrence, skipping duplicate"
                    )
                    continue
                if tname:
                    seen_tool_names.add(tname)
                tools.append(tool)

        logger.info(f"Total MCP tools loaded across all servers: {len(tools)}")
    else:
        logger.warning("No MCP servers enabled — agent will run without MCP tools")

    if not tools:
        logger.info(
            "No MCP tools loaded — agent will run with LLM-only capabilities. "
            "Add MCP servers in agent_config/mcp_servers.json if tools are needed."
        )

    async def _reload_mcp_tools() -> list[BaseTool]:
        """Reconnect to all MCP servers and return fresh tools (after token refresh)."""
        if token_manager:
            await token_manager.get_valid_token()
        fresh_configs = _build_all_server_configs()
        reloaded: list[BaseTool] = []
        for srv_name, srv_cfg in fresh_configs.items():
            try:
                client = MultiServerMCPClient({srv_name: srv_cfg})
                srv_tools = await asyncio.wait_for(
                    client.get_tools(),
                    timeout=settings.MCP_CONNECTION_TIMEOUT,
                )
                reloaded.extend(srv_tools)
            except Exception:
                logger.error(f"MCP reload failed for '{srv_name}'", exc_info=True)
        return reloaded

    if token_manager and sso_token and tools:
        tools = [
            _wrap_mcp_tool_for_sso_retry(t, token_manager, _reload_mcp_tools)
            for t in tools
        ]

    # Initialize the language model — provider and model ID come from
    # AgentForge deployer env vars (LLM_PROVIDER / LLM_MODEL_ID) with
    # Google Vertex AI as the default.
    import google.auth

    credentials, project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    _no_keepalive = httpx.Limits(max_keepalive_connections=0)

    model = ChatGoogleGenerativeAI(
        model=settings.LLM_MODEL_ID,
        temperature=0,
        credentials=credentials,
        project=project,
        client_args={"limits": _no_keepalive},
    )

    # Load subagent definitions from agents/ directory (markdown + frontmatter)
    agents_dir = CONFIG_DIR / "agents"
    logger.info(f"Loading subagents from {agents_dir}")

    tool_by_name = {t.name: t for t in tools}
    skills_base = CONFIG_DIR / "skills"

    # Main agent skills — one subdirectory per skill (registry materializes <skill>/SKILL.md)
    main_skills_path: list[str] = []
    if skills_base.is_dir():
        for skill_dir in sorted(p for p in skills_base.iterdir() if p.is_dir()):
            if (skill_dir / "SKILL.md").is_file():
                main_skills_path.append(str(skill_dir))
                logger.info(f"Main agent skill loaded: {skill_dir}")

    subagents_config: list[SubAgent] | None = None
    if agents_dir.is_dir():
        subagents_config = []
        for agent_file in sorted(agents_dir.glob("*.md")):
            config = _parse_agent_frontmatter(agent_file)
            name = config.get("name", agent_file.stem)

            # Use model from frontmatter, fall back to platform-injected default
            model_name = config.get("model") or settings.LLM_MODEL_ID
            model = None
            if model_name:
                logger.info(f"Subagent '{name}' using model: {model_name}")
                model = ChatGoogleGenerativeAI(
                    model=model_name,
                    temperature=0,
                    credentials=credentials,
                    project=project,
                    client_args={"limits": _no_keepalive},
                )

            sa: SubAgent = SubAgent(
                name=name,
                model=model,
                description=config.get("description", ""),
                system_prompt=config.get("body", ""),
            )

            # Resolve tool names to loaded MCP tools
            yaml_tool_names = config.get("tools", [])
            if yaml_tool_names:
                resolved = [
                    tool_by_name[n] for n in yaml_tool_names if n in tool_by_name
                ]
                missing = [n for n in yaml_tool_names if n not in tool_by_name]
                if missing:
                    logger.warning(
                        f"Subagent '{name}' references unknown tools: {missing}"
                    )
                sa["tools"] = resolved

            # Resolve skill names to paths under skills/
            skill_names = config.get("skills", [])
            if skill_names:
                skill_paths: list[str] = []
                for skill_name in skill_names:
                    skill_dir = skills_base / skill_name
                    if skill_dir.exists():
                        skill_paths.append(str(skill_dir))
                        logger.info(f"Subagent '{name}' skill loaded: {skill_dir}")
                    else:
                        logger.warning(
                            f"Subagent '{name}' skill not found: {skill_dir}"
                        )
                if skill_paths:
                    sa["skills"] = skill_paths

            subagents_config.append(sa)
        logger.info(f"Loaded {len(subagents_config)} subagents")
    else:
        logger.warning(f"Agents directory not found at {agents_dir}")

    # Load system prompt (identity + routing + behavior from system-prompt.md)
    system_prompt = get_system_prompt()
    logger.info("Loaded system prompt from agent_config/system-prompt.md")

    if not main_skills_path:
        logger.warning(f"No skill directories with SKILL.md under {skills_base}")

    backend = get_backend()

    # Resolve checkpointer and store
    checkpointer = None
    store = None
    pg_ctx = None

    if settings.USE_INMEMORY_SAVER:
        checkpointer = get_global_checkpoint()
        store = get_global_store()
        logger.info(
            f"Using in-memory checkpoint={type(checkpointer).__name__} "
            f"store={type(store).__name__}"
        )
    else:
        logger.info("Using PostgreSQL checkpoint")
        pg_ctx = AsyncPostgresSaver.from_conn_string(settings.database_uri)
        checkpointer = await pg_ctx.__aenter__()
        logger.info(f"PostgreSQL checkpointer ready: {type(checkpointer).__name__}")
        if hasattr(checkpointer, "setup"):
            await checkpointer.setup()

    logger.info(
        f"Creating deep agent with checkpointer={type(checkpointer).__name__ if checkpointer else None} "
        f"store={type(store).__name__ if store else None}"
    )

    try:
        agent = create_deep_agent(
            model=model,
            system_prompt=system_prompt,
            skills=main_skills_path,
            tools=tools,
            subagents=subagents_config,
            backend=backend,
            checkpointer=checkpointer,
            store=store,
        )
        logger.info("Deep agent initialized successfully")
        yield agent
    finally:
        if pg_ctx is not None:
            await pg_ctx.__aexit__(None, None, None)
