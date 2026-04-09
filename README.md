# Agent workspace template (Cookiecutter / Cruft)

This repository is a **[Cookiecutter](https://cookiecutter.readthedocs.io/)** template (use with **[Cruft](https://cruft.github.io/cruft/)** to track updates). The generated Python project lives under the directory named `{{cookiecutter.project_slug}}`.

## Generate a workspace locally

```bash
pip install cookiecutter
cookiecutter . --no-input \
  org=my-org \
  agent_name=support-bot \
  project_slug=my-org-support-bot
```

Or interactively:

```bash
cookiecutter .
```

## Using Cruft

```bash
pip install cruft
cruft create https://github.com/your-org/template-agent.git
```

After generation, commit the `.cruft.json` file Cruft adds so you can run `cruft update` when the template changes.

## Layout

| Path | Purpose |
|------|---------|
| `cookiecutter.json` | Template variables |
| `{{cookiecutter.project_slug}}/` | Rendered project (FastAPI agent, `agent_config/`, `Containerfile`) |

CI runs tests from `{{cookiecutter.project_slug}}/` — see `.github/workflows/test.yml`.
