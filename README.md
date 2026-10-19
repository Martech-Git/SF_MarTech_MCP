# SF_MarTech_MCP
This repository hosts the MCP server for SFMC and Data360 from Salesforce

Start with `docs/SPEC.md` (build spec) and `CLAUDE.md` (working rules).

Status: milestones 1 and 2. The server runs on Cloud Run, authenticates client API keys, enforces the policy bundle in `policy/`, audits every call into a hash chain, and exposes one tool, `health`. Salesforce tools start in milestone 3. Deployment steps: `docs/DEPLOY_M1_M2.md`. Setup handoff with what to send back: `docs/SETUP_HANDOFF_DEV.md`.
