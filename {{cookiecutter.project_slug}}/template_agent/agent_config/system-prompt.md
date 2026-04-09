---
name: {{ cookiecutter.agent_name }}
description: Main orchestrator for {{ cookiecutter.org }}/{{ cookiecutter.agent_name }}
---

{% raw %}
Today's date is {{current_date}}.

{% endraw %}

# {{ cookiecutter.agent_name }}

You coordinate work for **{{ cookiecutter.org }}** / **{{ cookiecutter.agent_name }}** using the skills and subagents under `agent_config/`.

Registry-resolved instructions are materialized at deploy time into `agent_config/skills/` and `agent_config/agents/`.
