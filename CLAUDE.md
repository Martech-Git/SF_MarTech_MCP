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

Added in milestone 1.
