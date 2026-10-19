# SF_MarTech_MCP

A governed MCP server for Salesforce Marketing Cloud Engagement (SFMC) and Data 360. Approved client integrations call it with their own API keys. Every tool call passes a fixed enforcement pipeline before anything reaches Salesforce.

## Source of truth

`docs/SPEC.md`. Read it before any change. API details and their verification status live in `docs/research/`.

## Rules for every session

- Build milestone by milestone (SPEC section 15.4). A milestone starts only after the previous one passes its done test.
- The tool registry and the policy bundle in `policy/` are the only places that grant capability.
- No write tool exists until the enforcement pipeline is complete (milestone 2).
- Never commit secrets, client API keys, Salesforce credentials or real subscriber data. Secret Manager holds every secret.
- When Salesforce behaves differently from the spec, stop and ask before changing the design.
- Work on a feature branch and open a PR into `dev`. `main` is prod.
- Rows marked UNVERIFIED in `docs/research/` get checked against the sandbox before code depends on them.

## Writing style

Code comments, docs and UI copy follow these rules: no em dashes, short sentences, no filler vocabulary, plain statements of what code does.

## Build and test commands

Python 3.12. From the repo root:

```bash
python3.12 -m venv .venv && .venv/bin/pip install --require-hashes -r requirements-dev.lock
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy && .venv/bin/pytest -q
```

Run locally with in-memory stores and the admin page open to one dev email (local only):

```bash
SFMCP_ENV=local SFMCP_KEY_PEPPER=$(openssl rand -hex 24) SFMCP_DEV_ADMIN_EMAIL=you@example.com PYTHONPATH=src .venv/bin/python -m sf_mcp
```

After changing dependencies in `pyproject.toml`, regenerate both lockfiles with `uv pip compile` for Python 3.12 on `x86_64-manylinux_2_28` with `--generate-hashes` (`requirements.lock`, and `requirements-dev.lock` with `--extra dev`).

Log messages are static strings. Never put request, Salesforce or secret values in a log message; structured fields outside the allowlist in `logging_setup.py` are dropped.

Deployment: `docs/DEPLOY_M1_M2.md`. Cloud Build runs the same checks before it builds the image.
