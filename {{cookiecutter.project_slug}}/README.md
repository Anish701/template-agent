# {{ cookiecutter.project_slug }} ({{ cookiecutter.org }}/{{ cookiecutter.agent_name }})

[![Python 3.12+](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

Generated agent workspace: SSE streaming, conversation management, and Langfuse tracing.

## Quick Start

**Prerequisites:** Python 3.12+, PostgreSQL, Google AI API credentials

```bash
cd {{ cookiecutter.project_slug }}
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
cp .env.example .env          # edit with your config
uv run python -m template_agent.src.main
```

The [template-mcp-server](https://github.com/redhat-data-and-ai/template-mcp-server) must be running before starting the agent.

## API

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Health check |
| `/v1/stream` | POST | Stream chat (SSE) |
| `/v1/history/{thread_id}` | GET | Conversation history |
| `/v1/threads/{user_id}` | GET | List user threads |
| `/v1/feedback` | POST | Record feedback |

```bash
curl -X POST http://localhost:5002/v1/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello", "thread_id": "t1", "user_id": "u1", "stream_tokens": true}'
```

Client examples (Streamlit, Python async) are in [`examples/`](./examples/).

## Configuration

| Variable | Default | Required |
|---|---|---|
| `AGENT_HOST` | `0.0.0.0` | No |
| `AGENT_PORT` | `5002` | No |
| `PYTHON_LOG_LEVEL` | `INFO` | No |
| `POSTGRES_USER` | `pgvector` | Yes |
| `POSTGRES_PASSWORD` | `pgvector` | Yes |
| `POSTGRES_DB` | `pgvector` | Yes |
| `POSTGRES_HOST` | `pgvector` | Yes |
| `POSTGRES_PORT` | `5432` | Yes |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | — | Yes |
| `LANGFUSE_PUBLIC_KEY` | — | No |
| `LANGFUSE_SECRET_KEY` | — | No |
| `LANGFUSE_BASE_URL` | — | No |
| `AGENT_SSL_KEYFILE` | — | No |
| `AGENT_SSL_CERTFILE` | — | No |

## Project Structure

```
template_agent/
├── src/
│   ├── core/
│   │   ├── agent.py          # Agent initialisation + subagent loading
│   │   ├── manager.py        # AgentManager, SSE streaming
│   │   ├── prompt.py         # System prompt loader
│   │   └── backend.py        # Shell backend (isolated venv)
│   ├── routes/
│   │   ├── stream.py         # POST /v1/stream
│   │   ├── history.py        # GET  /v1/history
│   │   ├── threads.py        # GET  /v1/threads
│   │   ├── health.py         # GET  /health
│   │   └── feedback.py       # POST /v1/feedback
│   ├── api.py                # FastAPI app + lifespan
│   ├── main.py               # Uvicorn entry point
│   ├── schema.py             # Pydantic models
│   └── settings.py           # Env config
├── agent_config/
│   ├── system-prompt.md      # Orchestrator prompt
│   ├── agents/               # Subagent definitions (YAML + MD)
│   └── skills/               # Skill documents per agent
└── tests/
    ├── agents/               # Agent-level tests (LLM-as-judge)
    ├── core/                 # Core unit tests
    └── routes/               # API route tests
```

## Testing & Quality

### Running Tests

```bash
# All tests
pytest

# With coverage
pytest --cov=template_agent.src --cov-report=html

# Agent-level tests only
pytest tests/agents/ -v

# Specific agent tests
pytest tests/agents/test_analyst.py -m analyst -v
pytest tests/agents/test_publisher.py -m publisher -v
pytest tests/agents/test_orchestrator.py -m orchestrator -v

# Single evaluation
pytest tests/agents/test_analyst.py -m analyst -k "eval-1" -v

# Code quality
ruff check . && ruff format .
pre-commit run --all-files
```

### Agent Tests

Tests are organized by agent (orchestrator + subagents), each with its associated skill and tools:

**Analyst** (`test_analyst.py`)
- Skill: `bmi-report`
- Tools: `calculate_bmi`, `search_web`
- Evals: `template_agent/agent_config/skills/bmi-report/evals/evals.json`

**Publisher** (`test_publisher.py`)
- Skill: `email-formatter`
- Tools: `send_email`
- Evals: `template_agent/agent_config/skills/email-formatter/evals/evals.json`

**Orchestrator** (`test_orchestrator.py`)
- Skill: `client-intake`
- Subagents: Analyst + Publisher
- Evals: `template_agent/agent_config/skills/client-intake/evals/evals.json`

Test results saved to `tests/workspaces/{agent}-workspace/eval-{id}/`:
- `outputs/report.md` - Agent output
- `outputs/grading.json` - LLM judge evaluation results

## Deployment

```bash
podman-compose up -d --build
```

For production: configure SSL certs (`AGENT_SSL_KEYFILE`, `AGENT_SSL_CERTFILE`), use managed PostgreSQL, and enable Langfuse tracing.

## Links

- [Issues](https://github.com/redhat-data-and-ai/template-agent/issues)
- [template-mcp-server](https://github.com/redhat-data-and-ai/template-mcp-server)
