"""System prompt loader for the template agent.

Loads the system prompt from agent_config/system-prompt.md and injects
runtime values like the current date.
"""

from datetime import datetime
from pathlib import Path

_CONFIG_DIR = Path(__file__).parent.parent.parent / "agent_config"

# Built without literal brace pairs so Cookiecutter does not parse this file as Jinja.
_DATE_PLACEHOLDER = "{" * 2 + "current_date" + "}" * 2


def get_current_date() -> str:
    """Get the current date in a formatted string.

    Returns:
        The current date formatted as "Month Day, Year" (e.g., "December 25, 2024").
    """
    return datetime.now().strftime("%B %d, %Y")


def get_system_prompt() -> str:
    """Load the system prompt from ``system-prompt.md``.

    Reads the markdown template from ``agent_config/system-prompt.md``
    and replaces the ``current_date`` placeholder with today's date.

    Returns:
        The fully rendered system prompt string.
    """
    template_path = _CONFIG_DIR / "system-prompt.md"
    template = template_path.read_text()
    return template.replace(_DATE_PLACEHOLDER, get_current_date())
