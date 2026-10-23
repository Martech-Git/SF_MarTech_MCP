# Data 360 (Data Cloud) API research for the headless marketing spec
Version 1.0. Date 2026-10-13. Input to the v2.0 headless design spec (DMT-02).

Method: a research subagent used web search. developer.salesforce.com and help.salesforce.com returned 403 or blank pages, so their content comes from search extracts. The forcedotcom/d360-mcp-server GitHub source was read directly and is the most concrete evidence for endpoint paths. UNVERIFIED marks anything not tied to a primary source. Credits are Flex Credit base-tier multipliers.

Auth codes used below:

- CORE. A normal Salesforce OAuth token against https://{MyDomain}/services/data/vXX.X/ssot/... (Connect API). Scopes api and cdp_api, plus cdp_query_api for SQL. Salesforce's own d360-mcp-server uses client_credentials here with no token exchange, so it works server to server.
- A360. A core token exchanged at POST /services/a360/token for a tenant token and tenant URL. The documented first step is JWT bearer, also server to server. The External Client App must have "Issue JWT-based access tokens for named users" OFF.
- MCP-H. The hosted MCP server. Authorization code plus PKCE for a named user only.

## 1. Segments

| Operation | API/tool | Auth | Sync | Limits/credits | Status | Src |
|---|---|---|---|---|---|---|
| Create | POST /ssot/segments; MCP d360_segment_create | CORE | Sync (definition only) | 9,950 active segments | GA | S1, S3 |
| Update | PATCH /ssot/segments/{segmentApiName} | CORE | Sync | | GA | S1, S2 |
| Publish on demand | POST /ssot/segments/{segmentId}/actions/publish, no body | CORE | Async, writes Segment Membership DMO | 50 concurrent standard publishes; not for real-time segments; Segmentation 50 credits per 1M rows | GA | S5, S4, S11 |
| Scheduled publish | publishSchedule (NoRefresh/One/Two/Four/Six/Twelve/TwentyFour), publishScheduleStartDateTime, publishScheduleEndDate on create/update | CORE | Async | Standard 12-24 h, max 2 scheduled publishes/day. Rapid 1-4 h, max 20 rapid segments, 7-day event window, chosen at creation only | GA | S3, S4, S32 |
| Deactivate | POST /ssot/segments/{apiName}/actions/deactivate | CORE | Sync | | Repo only; official reference UNVERIFIED | S3 |
| Population count | No dedicated endpoint (UNVERIFIED). Options: GET /ssot/segments/{segmentApiName}/members (paged), SQL COUNT over the membership DMO, segmentPopulation in activation history | CORE | Sync | Real-time and Dynamic segments have no counts | GA | S6, S7 |
| Delete | DELETE /ssot/segments/{segmentApiName} | CORE | Sync | | GA | S3 |

Segment types (segmentType): Ui, Dbt, Realtime, Waterfall, Lookalike, Dynamic, EinsteinGptSegmentsUI.

Criteria format. includeCriteria and excludeCriteria are escaped JSON strings with no published schema (UNVERIFIED). The documented programmatic route is segmentType Dbt with SQL in includeDbt. Validation: select only the SegmentOn primary key (plus key qualifiers); the first table must be a profile DMO; joins only on relationship keys; no aggregates, aliases or *; SELECT only. Real-time segments need segmentOnDataGraph, allow no exclusions or nested batch segments, max 35. Waterfall segments max 20.

## 2. Calculated insights

| Operation | API/tool | Auth | Sync | Limits/credits | Status | Src |
|---|---|---|---|---|---|---|
| Define | POST /ssot/calculated-insights (apiName ending __cio, SQL expression, definitionType CALCULATED_METRIC or STREAMING_METRIC, publishScheduleInterval One/Six/Twelve/TwentyFour/SystemManaged/Streaming/NotScheduled). Validate with POST .../actions/validate | CORE | Sync | 300 CIs per tenant, drafts included | GA | S3, S4 |
| Run | POST /ssot/calculated-insights/{ci}/actions/run; status via POST .../actions/refresh-status | CORE | Async | Runs over 2 h may be killed; no run when inputs unchanged; batch CI billed as Prep, 40 per 1M rows | GA | S3, S10, S11 |
| Read results | GET /ssot/insight/calculated-insights/{ci}, GET /api/v1/insight/calculated-insights/{ci} (A360), or SQL over the __cio object | CORE/A360 | Sync | 4,999 rows per page; Queries 3 per 1M rows | GA | S3, S11 |
| Streaming insights | STREAMING_METRIC, interval Streaming | CORE | Continuous | Unusable in segments; Streaming Pipeline 3,500 per 1M rows | GA | S10, S11 |

## 3. Activations to SFMC Engagement

| Operation | API/tool | Auth | Sync | Limits/credits | Status | Src |
|---|---|---|---|---|---|---|
| Create target | POST /ssot/activation-targets, platformType SalesforceMarketingCloud plus a connector. Needs the SFMC connection set up in Data 360 first; creating that connection by API UNVERIFIED | CORE | Sync | 300 targets | GA | S3, S1 |
| Create activation | POST /ssot/activations: name, refreshType FULL_REFRESH or INCREMENTAL, dataSpaceName, activationTargetName, segmentApiName or marketSegmentId, contactPointsConfig, attributesConfig, related-DMO filters, staticDataConfig (v66) | CORE | Sync | One activation per segment per target; 100 attributes; related attributes 300 across up to 4 DMOs, 25 records each; segments over 150M records with related attributes do not activate | GA | S1, S3, S4 |
| Update, enable, disable | PUT /ssot/activations/{id}; enable and disable endpoints from v67.0 | CORE | Sync | | GA | S1 |
| Refresh | No separate push call; data flows when the segment publishes (schedule or on demand) | | Async | Activation 60 per 1M rows | GA | S8, S11 |

Landing in SFMC. The segment becomes a shared, sendable data extension in Contact Builder under Shared Data Extensions, Customer 360 Segments, in a "Data 360 segments" subfolder created on first publish. Name format segmentName_activationName_segmentID_activationID. Only the chosen BU or MID sees it. Each refresh overwrites the previous data. Related attributes arrive as JSON in one column. Subscriber Key comes from the Contact Point DMO. No latency SLA documented (UNVERIFIED); the publish schedule bounds it in practice.

## 4. Predictions (AI Models, formerly Einstein Studio, renamed April 2026)

| Operation | API/tool | Auth | Sync | Limits/credits | Status | Src |
|---|---|---|---|---|---|---|
| Build model | /ssot/machine-learning/ model-setup and configured-models CRUD plus activate | CORE | Async | | UI GA; 44 API ops seen in repo, official reference UNVERIFIED | S3 |
| BYOM | Vertex AI (service account or key), SageMaker, Databricks. BigQuery ML is absent from the platform list | CORE | | | GA | S13 |
| Scoring job | /ssot/machine-learning/prediction-job-definitions CRUD, activate via PATCH; run with POST /ssot/machine-learning/jobs | CORE | Async, batch or streaming | Inferences usage type, per unique inference for internal and BYOM models; multiplier UNVERIFIED | GA | S3, S12, S14 |
| On-demand scoring | POST /ssot/machine-learning/predict | CORE | Sync | Up to 200 rows per call | Repo | S3 |

Scores land in an output DMO named when the job is created. Once related to the segment's target entity, segments can filter on it. Read scores with query-sql or the Profile API.

## 5. Query

| Operation | API/tool | Auth | Sync | Limits/credits | Status | Src |
|---|---|---|---|---|---|---|
| SQL via Connect API | POST /ssot/query-sql; GET /{id}, /{id}/rows; DELETE /{id} | CORE (docs show tenant host; repo uses core host) | First chunk sync, then async | No row cap; results kept 24 h | GA | S16, S3 |
| Query API V3 | POST /api/v3/query (ASYNC or ADAPTIVE); GET /{id}, /chunks/{n}, /metadata; DELETE | A360, cdp_query_api | Async | 3 credits per 1M rows | V1/V2 legacy, no retirement date found | S15 |
| Profile | GET /api/v1/profile/{dmo}[/{id}] or /ssot/profile/{dmo} | A360 cdp_profile_api, or CORE | Sync | 50 fields; AND and equality filters only; 5-minute timeout | GA | S17 |
| Identity resolution | /ssot/identity-resolutions CRUD plus /actions/run-now | CORE | Async | | GA | S3 |
| Data Graph | GET /api/v1/dataGraph/{name}?lookupKeys=&live=, or /ssot/data-graphs/data/{entity}[/{id}] | A360 or CORE | Sync | One contact key per lookup; real-time graphs allow primary-key or key-qualifier lookups only | GA | S18 |

## 6. Ingestion API

| Operation | API | Auth | Sync | Limits | Status | Src |
|---|---|---|---|---|---|---|
| Streaming | POST {tenant}/api/v1/ingest/sources/{connector}/{object} | A360, cdp_ingest_api | Async, about every 3 min, plus 30 s or more before queryable | 200 KB per request; 250 req/s (another page says 5,000, conflicting); delete up to 200 records per call; Streaming Pipeline 3,500 per 1M rows | GA | S19, S4 |
| Bulk | /api/v1/ingest/jobs, PUT .../batches (CSV), close | A360 | Async | 150 MB per file; 100 files per job; 20 jobs/hour; 5 concurrent; open jobs purged after 7 days | GA | S19 |
| Real-time | Streaming endpoint when the DMO belongs to a real-time data graph | A360 | About 500 ms p95 end to end | Streaming only; append or update | GA | S20 |

## 7. Data actions back to GCP

| Operation | API | Auth | Sync | Limits | Status | Src |
|---|---|---|---|---|---|---|
| Create target | POST /ssot/data-action-targets, type WebHook (also Core, MarketingCloud) | CORE | Sync | 100 targets | GA | S3, S22 |
| Signing key | POST /ssot/data-action-targets/{apiName}/signing-key; HMACSHA256 in the x-signature header | CORE | Sync | Rotate yearly; new key takes 15 min | GA | S21 |
| Create action | POST /ssot/data-actions, triggered by DMO or CI row insert, update or delete | CORE | Near real time after about 15 min setup | 200 actions per tenant; DataObjectDataChgEvent envelope, no attribute picking; retry policy undocumented; events kept 4 days (blog) | GA | S3, S22 |

## 8. MCP surfaces

| Surface | Tools | Auth | Status | Src |
|---|---|---|---|---|
| Hosted Data 360 MCP, api.salesforce.com/platform/mcp/v1/data/data360 (sandbox paths conflict in docs) | search, payload_examples, execute over about 200 Connect operations, writes included (segments, activations, targets, CIs, data actions, identity resolution). Manage Data 360 permission for writes, View Data 360 for reads. Counts against Connect API limits and Flex Credits | MCP-H: ECA with mcp_api, refresh_token, cdp_api, JWT-based tokens ON. Authorization code is the only flow, which blocks headless use | GA (news 19 Aug 2026; Summer '26 note says July 2026) | S23-S26 |
| Data 360 Legacy MCP | SQL query only | MCP-H | GA | S23 |
| forcedotcom/d360-mcp-server (stdio) | Same 3 facade tools over 187-201 operations: segment CRUD, publish, deactivate; activation and target CRUD; CI CRUD, run, query; data actions; query-sql, profile, data graph; event publish; GDPR; ML | Access token or client_credentials (api, cdp_api, cdp_query_api), headless | Developer preview; v1.0.0 on 2026-04-21; no read-only mode | S3 |

Caution: the repo's payload_examples.json samples for activation and data-action targets disagree with its own request classes. Build against the request classes.

## 9. Auth summary

Connect API with CORE and client_credentials (Run As integration user) is headless and covers sections 1 to 5 and 7. Ingestion, Query V3 and the tenant Profile and Data Graph endpoints need A360 via JWT bearer, also headless. Whether the A360 exchange accepts a client_credentials token is UNVERIFIED.

Confirmed scopes: cdp_api, cdp_ingest_api, cdp_query_api, cdp_profile_api. cdp_segment_api has no source (UNVERIFIED).

The hosted MCP ECA needs JWT-based tokens ON and the A360 exchange rejects JWT-format tokens, so the two paths need separate ECAs.

## 10. Marketing Cloud Next

- Runs on core plus Data 360; its segments are Data 360 segments on the same /ssot/segments endpoints.
- Campaigns generate Flows, managed through the Metadata and Tooling APIs.
- Direct Email Send API at api.salesforce.com/automation/actions360 offers single send, bulk send and preview; needs a sendDefinitionId, a JWT token with sfap_api, and High Scale Actions enabled.
- Salesforce states its APIs are incompatible with SFMC Engagement. Engagement journeys and sends keep running alongside it ("Engagement+").
- No Marketing Cloud Next MCP server confirmed; Campaign Agent is UI only. One Dreamforce page lists MCP access to journeys and flows as "GA October '26" (UNVERIFIED).
- Sources S29, S30, S31.

## Gaps

- Hosted Data 360 MCP cannot run headless. Use the Connect API directly, or self-host the open-source server with client_credentials.
- No segment count endpoint; no counts at all for real-time or dynamic segments.
- includeCriteria schema undocumented; use Dbt SQL segments.
- Creating the Data 360 to SFMC connection by API UNVERIFIED; no endpoint pushes an activation independently of a segment publish.
- API access for model training and Vertex model registration absent from the official reference.
- Data action retry behaviour undocumented.
- No Connect API rate limit published.

## Changes from July to October 2026

- Hosted Data 360 MCP reached GA in August, replacing the hosted query-only server, now "Data 360 Legacy".
- Data 360 Agent Skills GA in August 2026. Headless 360 MCP open beta in July.
- Connect API reference at v68.0 (Winter '27); activation enable and disable from v67.0.
- d360-mcp-server unreleased changes: segment_deactivate added, query calls moved to /ssot/query-sql, d360_query and d360_query_v2 removed (breaking).
- Flex Credit rate cards reissued 18 Aug and 31 Aug 2026; the 31 Aug card could not be parsed, figures UNVERIFIED.
- Dreamforce (15 to 17 Sep 2026): Headless Marketing via MCP, Campaign Agent, Agentic CDP GA announced.

## Sources

- S1 developer.salesforce.com/docs/data/connectapi/references/spec
- S2 developer.salesforce.com/docs/data/connectapi/guide/features_cdp_dbt_validations.html
- S3 github.com/forcedotcom/d360-mcp-server (tools/*.java, CHANGELOG.md, README.md)
- S4 help.salesforce.com/s/articleView?language=en_US&id=sf.c360_a_limits_and_guidelines
- S5 developer.salesforce.com/docs/marketing/marketing-cloud-growth/guide/mc-manage-segments-publish.html
- S6 developer.salesforce.com/docs/marketing/marketing-cloud-growth/guide/mc-manage-segments-get-members.html
- S7 help.salesforce.com/s/articleView?id=data.c360_a_create_a_realtime_segment.htm
- S8 help.salesforce.com/s/articleView?id=sf.c360_a_segments_in_marketing_cloud.htm
- S10 help.salesforce.com/s/articleView?id=sf.c360_a_differences_between_calculated_streaming_insights.htm
- S11 salesforce.com/en-us/wp-content/uploads/sites/4/assets/pdf/agentforce/Flex-Credits-Rate-Card-08.18.2026.pdf (and the 04.21.2026 card)
- S12 help.salesforce.com/s/articleView?id=data.c360_a_data_usage_types.htm
- S13 help.salesforce.com/s/articleView?id=data.c360_a_bring_your_own_model.htm
- S14 developer.salesforce.com/blogs/2024/12/using-ai-model-output-in-data-cloud-with-prediction-jobs
- S15 developer.salesforce.com/docs/data/data-cloud-query-guide/references/data-cloud-query-api-reference/query-api-migration.html
- S16 developer.salesforce.com/blogs/2025/08/boost-data-cloud-integrations-with-the-new-query-connect-api
- S17 developer.salesforce.com/docs/data/data-cloud-query-guide/references/data-cloud-query-api-reference/c360a-api-profile-call-overview.html
- S18 developer.salesforce.com/docs/data/data-cloud-query-guide/references/data-cloud-query-api-reference/c360a-api-data-graphs-overview.html
- S19 developer.salesforce.com/docs/data/data-cloud-int/references/data-cloud-ingestionapi-ref/c360-a-api-get-started.html
- S20 developer.salesforce.com/docs/data/data-cloud-int/references/data-cloud-ingestionapi-ref/c360-a-real-time-ingestion-api.html
- S21 developer.salesforce.com/docs/data/data-cloud-int/references/webhook-data-action-targets/c360a-api-webhook-data-action-targets-in-customer-data-platform.html
- S22 help.salesforce.com/s/articleView?id=sf.c360_a_data_action_target_in_customer_data_platform.htm
- S23 developer.salesforce.com/docs/platform/hosted-mcp-servers/guide/data360-mcp.html
- S24 developer.salesforce.com/docs/platform/hosted-mcp-servers/guide/security-best-practices.html; .../create-external-client-app.html
- S25 salesforce.com/news/stories/expanding-headless-360-enterprise-capabilities/
- S26 help.salesforce.com/s/articleView?id=release-notes.rn_cdp_2026_summer_data_360_mcp_server.htm
- S29 developer.salesforce.com/docs/marketing/marketing-cloud-growth/guide/mc-connect-apis-info.html; .../mc-manage-transactions-messages-direct-send.html
- S30 salesforce.com/blog/dreamforce-2026-5-ways-marketing-cloud-is-building-a-new-model-for-growth/
- S31 developer.salesforce.com/blogs/2026/06/the-mcp-server-for-marketing-cloud-engagement-is-now-ga
- S32 help.salesforce.com/s/articleView?language=en_US&id=sf.c360_a_rapid_segment_publish.htm
