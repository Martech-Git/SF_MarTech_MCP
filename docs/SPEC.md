# Salesforce Marketing MCP Server (sf-mcp) - Build Spec
Version 1.0. Date 2026-10-19. Status: draft for review. Repo: github.com/sfmc99/SF_MarTech_MCP (this file lives there as `docs/SPEC.md`).

`sf-mcp` is one governed MCP server through which approved client integrations drive Salesforce Marketing Cloud Engagement (SFMC) and Data 360. It is built, deployed and released on its own, separately from the Digital Marketing Twin. The twin becomes one client later.

Basis: Ankit's SFMC MCP server spec (shared 2026-10-19, to be saved as `docs/source_spec.md`) and the API research in `docs/research/`. This document adapts that spec to the decisions below and adds the Data 360 backend.

---

## 0. How to use this spec

1. Treat this file as the source of truth. Build milestone by milestone (Section 15). Each milestone ends with a done test, and the next starts only after it passes.
2. The tool registry and the policy bundle are the only places that grant capability.
3. API paths come from the research files. Rows marked UNVERIFIED there get checked against the sandbox in milestone 3 before code depends on them. When Salesforce behaves differently from this spec, stop and ask.
4. No write tool exists until the enforcement pipeline is complete (milestone 2).

Principles:

- Fail closed. Unknown client, unknown tool, missing grant, policy engine error, missing approval or ambiguous BU all deny.
- Least privilege per client key, per Salesforce credential and per service account.
- A named human approves every irreversible or customer-facing action, on a surface that client keys cannot reach.
- The server persists no Salesforce payload data.
- The model and all Salesforce content are untrusted. Guardrails run in code and never depend on model behaviour.

---

## 1. Decisions

| ID | Decision | Choice |
|---|---|---|
| S1 | Scope | SFMC Engagement and Data 360. Tools for data extensions, content, journeys, test sends, tracking, segments, activations, calculated insights and prediction reads |
| S2 | Separation | Own repo, own deploy, own release cycle. The twin is a client like any other |
| S3 | Inbound auth | API keys, one per client integration, each mapped to grants in the policy bundle (Ankit, 2026-10-19) |
| S4 | Outbound auth | SFMC installed packages and Data 360 External Client Apps, client credentials flow, secrets in GCP Secret Manager (Ankit, 2026-10-19) |
| S5 | Human approvals | T3 approvals and admin actions happen on a web page behind Identity-Aware Proxy with Google sign-in. Client keys cannot approve |
| S6 | GCP setup | The GEO accelerator model: private GitHub repo `sfmc99/SF_MarTech_MCP`, `dev` and `main` branches, PR review, Cloud Build trigger, Cloud Run, Secret Manager |
| S7 | Language | Python 3.12, official MCP Python SDK, pydantic v2, FastAPI for the non-MCP routes. GEO and the twin are Python too |
| S8 | Credential split | SFMC Reader, Builder and Launcher packages. Data 360 reader and builder apps. Only `sf-launcher` holds the Launcher secret |
| S9 | Release | Prod starts in read-only mode. Writes switch on per BU after the R3 checklist (Section 14) is green |

S5 is a default awaiting Ankit's confirmation (open decision A1).

---

## 2. Architecture

```
 Client integrations (Claude Code, Agent SDK apps, the twin later)
        |  HTTPS, Authorization: Bearer <client API key>
+-------v-----------------------------------------------------+
| External HTTPS load balancer + Cloud Armor (WAF, rate cap)  |
+-------+------------------------------+----------------------+
        | /mcp                         | /approvals, /admin
        |                              | (IAP, Google sign-in)
+-------v------------------------------v----------------------+
| sf-mcp (Cloud Run)                                          |
| client auth | 10-step pipeline | policy bundle | approvals |
| audit chain | SFMC backend | Data 360 backend | admin UI   |
+-------+---------------------------+-------------------------+
        | signed execute            | T0 to T2 calls
+-------v-----------+               | (Reader, Builder, Data 360 apps)
| sf-launcher       |               |
| (internal only)   |               |
| Launcher package  |               |
+-------+-----------+               |
        |                           |
+-------v---------------------------v-------------------------+
| SFMC Engagement REST + SOAP   |   Data 360 Connect API      |
+-------------------------------------------------------------+
 Trusted stores: Secret Manager, Firestore (sf-mcp database), policy bundle
 Telemetry: Cloud Logging (locked bucket) + BigQuery sink, Cloud Trace
```

Trust boundaries. Clients, models and every value read from Salesforce are untrusted. The policy bundle, Secret Manager and Firestore are trusted. Salesforce is reached only with per-MID SFMC tokens and Data 360 app tokens from least-privilege integrations.

Ingress. Clients outside GCP, such as Claude Code on a laptop, need a public route, so `sf-mcp` sits behind an external HTTPS load balancer with Cloud Armor. Cloud Run ingress is set to internal plus load balancer. `sf-launcher` takes internal ingress only and admits the `sf-mcp` service account alone.

---

## 3. Client authentication with API keys

Format: `sfmcp_<env>_<key_id>_<secret>`. The key_id is a public identifier. The secret is 32 random bytes, base64url.

Issue and storage:

- A platform_admin issues keys on the admin page (Section 4). The full key shows once, at issue.
- Firestore `keys/{key_id}` stores: client_id, HMAC-SHA256 of the secret, environment, status, created_at, expires_at, issued_by, and revocation details.
- Everything that grants capability lives in `policy/clients.yaml`, keyed by client_id: client name, owner (a named person), grants (roles per BU, Section 4), allowed sources (CIDR list or `*`), max tier, enabled flag. Keys hold no grants of their own, so a grant change always goes through a PR.
- The HMAC pepper lives in Secret Manager. No plaintext key is stored anywhere server side.
- Keys expire after 90 days at most. Each client may hold two active keys at once, for overlap during rotation.

Validation on every request, as pipeline step 1:

- Parse `Authorization: Bearer <key>`. Look up key_id, compare the HMAC in constant time, and check status, expiry, environment and source address.
- Failed attempts count per source IP and per key_id. Ten failures in five minutes block the source for 15 minutes and raise an alert.
- Key status is cached for up to 10 seconds, so a revocation takes effect within that window.

Human attribution:

- A client may send `X-Acting-User: <email>`. The server writes it to audit as "asserted by <key_id>" and to the plan record for self-approval checks. It never feeds authorization.
- A later release can accept a signed user assertion from a trusted client (for example the twin gateway, verified against its JWKS). Until then, grants come from the key alone.

Client-side handling (security). A client API key is a bearer credential: anyone holding it acts with its grants. Clients keep it in a secret store or an environment variable. In Claude Code, `.mcp.json` references it through environment variable expansion, for example `"Authorization": "Bearer ${SFMCP_API_KEY}"`, and the key itself never enters a repo.

---

## 4. Roles, grants and approvals

Client roles, granted to keys per BU in `policy/grants.yaml`:

| Role | Can do | Approval needed for |
|---|---|---|
| viewer | Read schemas, masked rows, assets, journey and automation status, tracking, segments, insights, scores | none |
| content_editor | viewer, plus create and update content assets in allowed folders, plus test sends to seed lists | Updates to assets in production folders (T2 confirm) |
| data_operator | viewer, plus DE row upserts up to the cap, allowlisted imports, segment and insight drafts, segment publishes | Imports over the cap, publishes (T2 confirm); publishes that feed live journeys (T3) |
| campaign_operator | viewer, plus journey drafts, activations, journey launch, pause and stop, automation start | Every activation, launch, stop and automation start (T3) |

Human roles, granted to Google identities through IAP and Google groups:

| Role | Can do |
|---|---|
| approver | Approve or reject pending T3 actions for the BUs in the grant. Never their own requests |
| platform_admin | Issue and revoke keys, toggle kill switches and read-only mode, view audit. No Salesforce data by default |

Client keys never hold human roles. Roles add up per BU: a key can be content_editor in BU A and viewer in BU B. A key with no grants sees zero tools.

T3 flow:

1. The client calls the tool with `mode: "plan"`. The server runs pipeline steps 1 to 8, returns the plan and `plan_hash`, and creates a pending approval.
2. Approvers for that BU see the plan on `/approvals` (IAP). The page shows operations, targets, counts, the diff and any test-send evidence.
3. An approver decides. The server rejects a decision when the approver equals the key owner or the asserted acting user on the plan.
4. The client calls the tool again with `mode: "execute"`, the `plan_hash`, the `approval_id` and an `idempotency_key`.
5. The server re-runs the pipeline, recomputes the target fingerprint, checks the audience band and both windows, then sends a signed request to `sf-launcher`.

Windows: an approval request expires 24 hours after creation if nobody decides. An approved plan must execute within 30 minutes of the decision.

Approval records live in Firestore `approvals/{approval_id}`: run reference, plan_hash, tool, tier, BU, environment, key_id, asserted user, approver, decision, comment, timestamps, expiries. They hold no Salesforce data.

---

## 5. Enforcement pipeline

Every tool call passes these ten steps in code, in this order. A failing or erroring step denies the call, and nothing can skip or reorder a step.

1. Authenticate. Valid client key (Section 3).
2. Kill switches. Global, per tool, per BU and read-only mode; any one engaged denies with KILL_SWITCH.
3. Schema validation. pydantic strict models, `extra="forbid"`, bounded strings, enums for modes, regex for external keys, MIDs and segment API names.
4. Authorize. Key grants: role, tool, BU and environment, looked up in the policy bundle.
5. Resource allowlists. DE keys, Content Builder folders, template IDs, journey and automation IDs, seed lists, segment API names, activation targets. Default deny. A folder grant on a BU's "Data 360 segments" shared folder admits data extensions created by approved activations.
6. Limits. Per-call caps (rows per upsert, rows per page, asset size), per-key and per-BU rate limits, a tenant-level bucket below SFMC's 2,500 sync requests per minute, daily send and import quotas, Data 360 credit quotas per BU per day, annual SFMC API call tracking.
7. Content and data rules. Protected columns; AMPscript and SSJS blocked unless the grant allows scripting; HTML size and link-domain allowlist; email rules (Section 8); segment SQL rules: SELECT only, a profile DMO first, joins on relationship keys, no aggregates, aliases or `*`.
8. Risk tier. Decides direct execution, a confirmed dry run, or a human approval (Section 6).
9. Execute. Idempotency key enforced. Launcher tools go to `sf-launcher` as a signed request.
10. Verify and audit. Post-condition checks (row count delta, asset version, journey status, publish status), then the audit event. For T2 and T3 the audit write is synchronous; if it fails, the action does not run.

---

## 6. Risk tiers and plan hashing

| Tier | Examples | Behaviour |
|---|---|---|
| T0 read | Describe a DE, query rows, get an asset, journey status, segment count, read scores | Execute. PII masked |
| T1 reversible write | Create a draft asset, create a draft segment or journey, upsert up to 500 rows into a non-sendable DE | Execute. Audit with before and after hashes |
| T2 impactful write | Update a production asset, import over 500 rows, upsert into a sendable DE, publish a segment, create an activation, test send, pause or resume a journey | Mandatory plan, then execute with the plan_hash |
| T3 irreversible or external | Activate or stop a journey, start an automation, publish a segment that feeds a live journey, deactivate a segment | Plan, then approval by a named human approver, then execute within the window |

`plan_hash` is SHA-256 over canonical JSON of tool, BU, environment, target IDs, operations and a target-state fingerprint:

| Tool | Fingerprint |
|---|---|
| journey_activate | Interaction ID, version number, modifiedDate, entry DE key, email asset IDs and versions, send classification key |
| segment_publish, activation_create | Segment API name, hash of the segment SQL, activation target, attribute list |
| email_test_send | Asset ID and version, seed list ID |
| asset_update (T2) | Asset ID and version, hash of the new content |
| de_upsert_rows (T2), import_submit | DE key, row count, hash of the payload or file reference |

Audience counts stay outside the hash. The plan records the count and a tolerance band, plus or minus 10 percent by default. At execute time the server re-reads the count, and a count outside the band denies with AUDIENCE_DRIFT. A Data 360 activation refreshes its data extension on the segment's publish schedule, so an exact count would void approvals after every refresh.

---

## 7. Tool catalog

Launcher tools (L) execute in `sf-launcher`. Every T2 and T3 tool takes `mode: "plan" | "execute"`; execute takes `plan_hash`, plus `approval_id` for T3. Every write takes an `idempotency_key` (UUID); a replay returns the original result.

SFMC backend:

| Tool | Tier | Min role | API (verify in milestone 3) |
|---|---|---|---|
| bu_list | T0 | viewer | Policy bundle only |
| de_describe | T0 | viewer | SOAP Retrieve DataExtension, DataExtensionField |
| de_query_rows | T0 | viewer | REST rowset with filter, projection, paging; SOAP Retrieve fallback |
| de_count | T0 | viewer | Rowset count; SOAP Retrieve fallback |
| de_create | T1 | data_operator | SOAP Create DataExtension |
| de_upsert_rows | T1/T2 | data_operator | REST /hub/v1/dataevents/key:{key}/rowset; async rows API above the cap |
| import_submit | T2 | data_operator | SOAP ImportDefinition Perform on an allowlisted definition |
| import_status | T0 | viewer | SOAP ImportResultsSummary |
| asset_search | T0 | viewer | REST POST /asset/v1/content/assets/query |
| asset_get | T0 | viewer | REST GET /asset/v1/content/assets/{id} |
| asset_create_draft | T1 | content_editor | REST POST /asset/v1/content/assets into allowlisted draft folders |
| asset_update | T1/T2 | content_editor | REST update by id; T2 in production folders |
| email_test_send (L) | T2 | content_editor | SOAP EmailSendDefinition Perform "test", allowlisted seed lists only |
| journey_list | T0 | viewer | REST GET /interaction/v1/interactions |
| journey_get_status | T0 | viewer | REST GET /interaction/v1/interactions/{id} with stats |
| journey_create_draft | T1 | campaign_operator | REST POST /interaction/v1/interactions |
| journey_update_draft | T1 | campaign_operator | REST PUT /interaction/v1/interactions; modifiedDate must match |
| journey_activate (L) | T3 | campaign_operator | REST POST publishAsync, poll publishStatus |
| journey_pause, journey_resume (L) | T2 | campaign_operator | REST pause and resume; standard journeys only |
| journey_stop (L) | T3 | campaign_operator | REST POST stop |
| automation_get_status | T0 | viewer | SOAP Retrieve Automation |
| automation_start (L) | T3 | campaign_operator | SOAP Perform start |
| tracking_summary | T0 | viewer | SOAP tracking events for one send, aggregated server side |

The source spec's `send_transactional` stays out of v1: the Transactional Messaging API has no suppression lists, so campaign email through it would bypass unsubscribes.

Data 360 backend:

| Tool | Tier | Min role | API (verify in milestone 3) |
|---|---|---|---|
| d360_query | T0 | viewer | POST /ssot/query-sql with projection, page caps and masking |
| segment_list, segment_get | T0 | viewer | GET /ssot/segments |
| segment_create_draft | T1 | data_operator | POST /ssot/segments, segmentType Dbt, publishSchedule NoRefresh |
| segment_update_draft | T1 | data_operator | PATCH /ssot/segments/{segmentApiName} |
| segment_count | T0 | viewer | Before publish: segment SQL wrapped in COUNT through query-sql. After publish: COUNT over the Segment Membership DMO |
| segment_publish | T2 or T3 | data_operator | POST /ssot/segments/{segmentId}/actions/publish. T3 when an activation of the segment feeds an active journey |
| segment_deactivate | T3 | campaign_operator | POST /ssot/segments/{apiName}/actions/deactivate (repo source only) |
| activation_create | T2 | campaign_operator | POST /ssot/activations to the configured SFMC target |
| activation_status | T0 | viewer | GET /ssot/activations/{id} |
| ci_define | T1 | data_operator | POST /ssot/calculated-insights, then .../actions/validate |
| ci_run | T2 | data_operator | POST /ssot/calculated-insights/{ci}/actions/run |
| ci_read | T0 | viewer | GET /ssot/insight/calculated-insights/{ci} |
| prediction_read | T0 | viewer | query-sql over a prediction output DMO or a federated score DLO |

Tool design rules:

- Names are verbs on nouns. Each description states what the tool does, its tier, its limits and when not to use it.
- Outputs are typed JSON: `{ status, data, meta: { tool_call_id, policy_version, bu, truncated, next_cursor } }`. Tool results wrap Salesforce values in a data envelope and never as free text.
- Tools carry MCP hints (readOnlyHint, destructiveHint, idempotentHint). Server enforcement never relies on them.
- A new tool enters through a registry entry, a policy entry and tests in the same PR. No dynamic or user-defined tools.
- The tool list a client sees is filtered by its grants, and every call is re-checked server side.

---

## 8. Email content rules

Checked in pipeline step 7 for asset_create_draft, asset_update, journey_create_draft and journey_activate:

- Emails come from approved templates (allowlisted template IDs, asset type 207 with slot content). Raw HTML (asset type 208) needs the `html:write` grant.
- Every email carries a profile center or unsubscribe link and the sender's physical address. Journey email activities use a commercial send classification.
- Link domains sit on the BU allowlist. Tracking parameters are allowed.
- AMPscript and SSJS stay blocked unless the grant allows scripting. Personalization strings reference allowlisted attributes only.
- HTML stays under 100 KB, below Gmail's 102 KB clipping point. Subjects stay under 150 characters, and a preheader must be present.

---

## 9. Salesforce credentials and client layer

All Salesforce traffic goes through two internal client modules, `sfmc/` and `d360/`. Tools never open HTTP or SOAP connections themselves.

SFMC, three installed packages per environment, each a server-to-server API integration:

| Package | Scopes | Held by |
|---|---|---|
| sfmcp-reader | Read on Data Extensions, Email, Journeys, Automations, Documents and Images, Saved Content, Lists and Subscribers; Tracking Events | `sf-mcp` |
| sfmcp-builder | Write on Data Extensions, Email, Journeys, Saved Content, Documents and Images. No Send, no Execute | `sf-mcp` |
| sfmcp-launcher | Email Send, Journeys Execute, Automations Execute | `sf-launcher` only |

Test sends need Email Send, which is why `email_test_send` runs in `sf-launcher`, restricted there to allowlisted seed lists.

Data 360, two External Client Apps per environment with the client credentials flow, each with its own Run As integration user:

| App | Permission set | Scopes | Held by |
|---|---|---|---|
| sfmcp-d360-reader | Read on the DMOs, segments, activations and insights in scope | api, cdp_api, cdp_query_api | `sf-mcp` |
| sfmcp-d360-builder | Manage segments, activations and calculated insights | api, cdp_api | `sf-mcp` |

Exact permission set names get confirmed in milestone 3. No hosted Salesforce MCP app gets created; those accept interactive login only.

Secret Manager, one secret per value, with per-secret IAM bindings only:

| Secret | Accessor |
|---|---|
| `sfmc-reader-client-id`, `sfmc-reader-client-secret` | `sf-mcp` SA |
| `sfmc-builder-client-id`, `sfmc-builder-client-secret` | `sf-mcp` SA |
| `sfmc-launcher-client-id`, `sfmc-launcher-client-secret` | `sf-launcher` SA |
| `d360-reader-client-id`, `d360-reader-client-secret` | `sf-mcp` SA |
| `d360-builder-client-id`, `d360-builder-client-secret` | `sf-mcp` SA |
| `sfmcp-key-pepper` | `sf-mcp` SA |
| `sfmcp-launcher-signing-key` | `sf-mcp` SA (sign), `sf-launcher` SA (verify) |

Client layer rules:

- Tenant subdomains, MIDs, the Data 360 My Domain URL and the Connect API version come from per-environment config, never from code.
- SFMC tokens: `POST /v2/token` with client credentials and `account_id` set to the target MID. Cache key (package, MID). Refresh at 80 percent of lifetime with single-flight. Memory only.
- Data 360 tokens: client credentials against the org token endpoint. Same cache rules.
- The client refuses any SFMC call without an explicit MID and re-checks the MID against the key's grants.
- Timeouts 10 seconds for sync calls. Retries with jittered exponential backoff on 429, 5xx and SOAP server faults only, honouring Retry-After, at most 3 attempts, never on 4xx validation errors. A circuit breaker per BU returns SFMC_UNAVAILABLE when open.
- Above the sync cap (500 rows) work becomes an async job: submit, return job_id, poll through a status tool. The model never waits in a loop.
- Cursors are opaque, signed by the server, and bound to the key, tool and target, so a client cannot forge offsets into another DE.
- Errors map to a closed set: NOT_FOUND, VALIDATION, PERMISSION, RATE_LIMITED, SFMC_UNAVAILABLE, D360_UNAVAILABLE, VERIFY_FAILED, AUDIENCE_DRIFT, KILL_SWITCH. Messages are sanitized so no echoed field value passes through.
- Secrets rotate every 90 days using SFMC staged secrets, inside SFMC's 180-day limit. An alert fires 60 days before any expiry.

---

## 10. Zero data retention and data handling

Server side, enforced by this build:

- No Salesforce response body, DE row, asset HTML, profile attribute or subscriber value is written to disk, Cloud Logging, Firestore, trace attributes or error reports.
- Logs carry structure only: tool, IDs, counts, durations, status codes, policy decision, and SHA-256 hashes of inputs and outputs.
- A redaction layer runs before every sink. Loggable fields come from an allowlist; everything else drops. Tests assert that seeded PII never appears in captured output.
- Tokens and request buffers live in memory only. No response caching.
- Approval and idempotency records hold the plan hash, target IDs and counts only. Idempotency keys expire after 24 hours.

Model side. Whatever a tool returns enters the client's model context. Zero retention there depends on each client's Anthropic agreement and surface. Until that is confirmed in contract for a client, its key gets masked data only.

Data minimization:

- Field classes per DE and per DMO in the policy bundle: pii, sensitive, public. Unclassified columns count as pii.
- T0 reads return masked pii values (for example `j***@d***.com`). Sensitive columns never return. No key holds `pii:read` in v1.
- Query tools enforce projection and page caps (default 50 rows, max 200). Counts and distributions are preferred over row dumps.
- Bulk movement never passes through the model. Imports reference files already on SFMC Enhanced FTP or an approved GCS-to-SFTP path.
- TLS 1.2 or later everywhere. CMEK on Firestore and log buckets if policy requires it.

---

## 11. Observability and audit

One immutable audit event per tool call:

| Field | Content |
|---|---|
| tool_call_id, trace_id | UUID, W3C trace ID |
| timestamp | RFC 3339, UTC |
| client | key_id, client name, key owner |
| asserted_user | `X-Acting-User` value, marked as asserted |
| tool, tier, mode | for example de_upsert_rows, T1, execute |
| bu, environment | MID, dev or prod |
| targets | DE key, asset ID, journey ID, segment API name |
| input_hash, output_hash | SHA-256 of canonical JSON |
| counts | Rows requested, written, rejected |
| policy | Decision, rule ID, bundle version |
| approval | approval_id, approver, plan_hash |
| upstream | SFMC or Data 360 request IDs, status codes, latency |
| outcome | success, denied, failed, verify_failed |

- Sink: Cloud Logging into a dedicated bucket with a retention lock (400 days by default), plus a BigQuery sink for analysis.
- Tamper evidence: each event carries the hash of the previous event for its BU. A daily job verifies the chain and alerts on gaps.
- Tracing: OpenTelemetry spans for auth, policy, each Salesforce call and verification, exported to Cloud Trace under the same no-payload rule.
- Metrics: calls by tool, tier and outcome; denials by rule; approval latency; Salesforce latency and 429 rate per BU; token refresh failures; circuit breaker state; Data 360 credit burn against quota.
- Alerts: a denial spike for one key, any T3 execution outside business hours, approvals decided within 10 seconds of the request, repeated VERIFY_FAILED, audit write failures, Salesforce auth failures, key issuance and revocation, kill-switch changes.
- Dashboards: an operator view (health, latency, errors) and a governance view (which key did what, where, with which approval), the second built on BigQuery.

---

## 12. Governance and change control

- Capability changes only through reviewed code. Adding a tool, widening a grant, adding a BU, DE, folder or seed list to an allowlist, or raising a limit is a PR with two approvals: one from platform or security, one from the marketing ops owner of the BU.
- Environments: dev (SFMC sandbox BU, Data 360 sandbox or demo data space, synthetic data) and prod, with staging added when a client deployment needs it. Separate GCP projects, separate Salesforce integrations, separate secrets. No prod credential exists outside the prod project.
- Promotion: the same container image moves from dev to prod by digest. Policy bundles are versioned and promoted the same way.
- Kill switches in Firestore, cached up to 10 seconds: global off, per tool, per BU, and read-only mode (T1 to T3 denied). Toggled by platform_admin on `/admin`, each toggle audited and alerted.
- Access reviews every quarter: export key grants, human role grants and usage per key; remove what is unused.
- Incident runbook: read-only mode, revoke the affected keys, rotate Salesforce secrets, review the audit chain for the affected BUs, restore by PR.
- Tool reference pages generate from the registry, so documentation cannot drift from behaviour.

---

## 13. GCP infrastructure (GEO model)

| Component | Choice | Notes |
|---|---|---|
| Source | Private GitHub repo `sfmc99/SF_MarTech_MCP` | `dev` deploys to dev, `main` deploys to prod. Feature branches, PR into `dev`, reviewer merges |
| CI/CD | Cloud Build triggers on merge to `dev` and `main` | Build, test, scan, push to Artifact Registry, deploy by digest. Each trigger deploys both `sf-mcp` and `sf-launcher` |
| Compute | Cloud Run gen2. `sf-mcp` min 1 instance in prod; `sf-launcher` internal | Streamable HTTP MCP transport. Request timeout sized for sync calls |
| Edge | External HTTPS load balancer, serverless NEG, Cloud Armor | WAF rules, rate limiting, optional source IP allowlist per client |
| Human pages | IAP on the `/approvals` and `/admin` backends | Google sign-in; access through Google groups per BU |
| Identity | One dedicated service account per service | `sf-mcp`: per-secret accessor (Section 9), Firestore user, log writer, trace agent, invoke `sf-launcher`. `sf-launcher`: per-secret accessor on its secrets only. Never the default compute account |
| Secrets | Secret Manager, per-secret IAM | No project-level secretAccessor grant |
| State | Firestore native, database `sf-mcp` | clients, approvals, idempotency, kill switches, audit chain heads. No Salesforce data |
| Audit | Cloud Logging bucket with retention lock, BigQuery sink | CMEK if required |
| Telemetry | Cloud Trace, Cloud Monitoring | Alert policies kept in the repo |
| Egress | Serverless VPC connector or direct VPC egress, Cloud NAT with static IP | Lets SFMC and Data 360 allowlist the server's IP |
| Supply chain | Artifact Registry, Binary Authorization | Images built in Cloud Build, scanned, signed, deployed by digest |
| Org guardrails | Org policies: no service account keys, no public buckets, restricted regions | VPC Service Controls in prod (A6) |

Containers run as non-root on a read-only filesystem from a distroless base, with dependencies pinned through a lockfile.

Two GEO audit findings shape this table: a project-level secretAccessor grant let one service read every secret, and the default compute account held Editor. Both are banned here.

---

## 14. R3 checklist

Writes switch on for a BU in prod only when every line is green as a tested artefact:

- Masking proven on production-shaped data.
- Row limits enforced and tested.
- Zero data retention in contract for each client surface that receives unmasked data, or masking stays absolute.
- Three SFMC packages and two Data 360 apps at least privilege, each with its own secrets.
- Launcher separation tested: `sf-mcp` cannot send, and `sf-launcher` refuses unsigned or unapproved requests.
- Plan, approval, execute and verify pass E2E, including drift, stale plan, self-approval and expired windows.
- Prompt-injection suite at zero escapes.
- Read-only mode drill completed in prod.
- BU owner and security sign-off recorded in the audit log.

---

## 15. Repository layout, conventions, testing and milestones

### 15.1 Layout

```
sf-mcp/
  CLAUDE.md              # pointers to docs/SPEC.md, build and test commands
  docs/
    SPEC.md              # this file
    source_spec.md       # Ankit's SFMC MCP server spec, verbatim
    research/            # the API research files
  src/
    sf_mcp/
      server.py          # MCP server, streamable HTTP; FastAPI for /approvals, /admin, /healthz
      auth/              # client key validation, source checks, lockout
      pipeline/          # steps.py (the ten steps in order), runner.py (runs them, then audits)
      policy/            # loader, evaluator
      tools/             # one folder per tool: schema.py, handler.py, description.md, test_<tool>.py
      sfmc/              # REST client, SOAP client, token cache, error mapper
      d360/              # Connect API client, token cache, error mapper
      approvals/         # plan hashing, fingerprints, approval store, approval pages
      admin/             # key issue and revoke, kill switches
      audit/             # event builder, redaction, hash chain
      telemetry/         # OpenTelemetry setup, metrics
    sf_launcher/         # signed-request verifier, Launcher token cache, launch handlers
  policy/                # grants.yaml, allowlists.yaml, limits.yaml, fields.yaml, quotas.yaml
  infra/                 # Terraform or deploy scripts per environment (A2)
  cloudbuild.yaml
  tests/
    unit/  contract/  policy/  redaction/  e2e/  evals/
```

### 15.2 Conventions

Python 3.12, mypy strict, ruff, pytest. No `Any` in `src/`. Handlers are pure functions of (validated input, context, client) and never touch logging or policy directly. A tool folder without schema, handler, description and tests fails CI.

### 15.3 Testing

- Unit: each pipeline step, key validation and lockout, plan hashing, fingerprints, cursor signing, error mapping, email and segment SQL rules.
- Policy: a table of (key grants, BU, tool, input) and the expected decision, with negative cases for every allowlist and limit, run on every policy change.
- Redaction: seeded PII in fixtures never appears in logs, traces or error output.
- Contract: recorded and scrubbed SFMC REST and SOAP fixtures and Data 360 Connect fixtures.
- E2E on the sandbox with synthetic data: approval flows, AUDIENCE_DRIFT, stale plan, self-approval, expired windows, kill switches, read-only mode, key revocation.
- Adversarial: instructions hidden in asset HTML, DE values, segment names and Data 360 attributes, run against Claude through the server. Pass means no tool call exceeds the key's grants.
- Load: the server's limiter trips before Salesforce returns 429s.

### 15.4 Milestones

1. Skeleton and infra. Repo, Cloud Build triggers, dev project setup, Cloud Run deploy of an MCP server with one health tool, load balancer and Cloud Armor, OpenTelemetry. Done when a merge to `dev` deploys by digest, traces show in Cloud Trace, and the image is signed.
2. Client auth, policy and audit. Key issue and validation, admin page behind IAP, policy loader, kill switches, audit with redaction and hash chain. Done when the policy and redaction suites are green, an unknown, revoked or expired key gets 401, and a key with no grants sees zero tools.
3. Salesforce clients and reads. Verification spikes first (below). Then token caches, SFMC and Data 360 clients, error mapper, all T0 tools with masking and signed cursors, a mock backend recorded from sandbox shapes. Done when contract tests are green, T0 reads work on the sandbox, and no payload appears in logs.
4. Writes at T1 and T2. Idempotency, plan and execute, fingerprints, post-condition checks, T1 and T2 tools on both backends, email and segment SQL rules. Done when replay, stale plan, cap exceeded and content-rule failures all deny in E2E.
5. Approvals, sf-launcher and T3. Approval store and `/approvals` page, `sf-launcher` with signed requests, every launcher tool. Done when no T3 path runs without a named approver in E2E, self-approval fails, expired windows deny, a config test proves `sf-mcp` holds no Launcher secret, and the injection suite passes.
6. Production readiness. Prod project, Salesforce integrations and secrets, VPC Service Controls, alerts and dashboards, runbook, access review export, R3 checklist evidence. Done when security signs off and the read-only drill passes in prod. Prod starts read-only.

Milestone 3 verification spikes:

| Spike | Question |
|---|---|
| V1 | SFMC REST rowset count and REST automation reads, or SOAP fallbacks |
| V2 | Data 360 query-sql accepts a COUNT wrapper around segment SQL; segment deactivate exists in the official API |
| V3 | Test send scope and user permission on the Launcher package |
| V4 | Activation data extension name, folder and refresh behaviour in the org |
| V5 | Data 360 permission sets for the reader and builder integration users |
| V6 | Connect API version to pin for the org |

---

## 16. Open decisions

| ID | Decision | Default until decided |
|---|---|---|
| A1 | Approver and admin sign-in | IAP with Google sign-in and Google groups per BU |
| A2 | Infrastructure as code | Terraform, unless the GEO deploy scripts are the team standard |
| A3 | GCP projects | `digital-marketing-twin` for dev; a new prod project in milestone 6 |
| A4 | Region | us-east1, next to the existing project's resources |
| A5 | First client keys | Claude Code for the build team against dev; the twin once its build starts |
| A6 | VPC Service Controls | Prod only, milestone 6 |
| A7 | v1 allowlists: BUs, DEs, folders, templates, seed lists, activation target | Sandbox BU only until provided |
| A8 | Caps | Sync rows 500, page 50 default and 200 max, audience band plus or minus 10 percent |
| A9 | Audit retention | 400 days |
| A10 | `pii:read` for any key | None in v1 |
| A11 | Approval windows | Request 24 hours, execute 30 minutes after the decision |
