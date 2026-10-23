# SFMC Engagement API research for the headless marketing spec
Version 1.0. Date 2026-10-13. Input to the v2.0 headless design spec (DMT-02).

Method: a research subagent used web search. WebFetch returned HTTP 403 on developer.salesforce.com, and help.salesforce.com served only its JS shell, so facts citing those sites come from search-indexed text of the official pages. Anything not confirmed that way is marked UNVERIFIED. Re-verify UNVERIFIED rows against the live org before the build relies on them.

URL prefixes: D = developer.salesforce.com/docs/marketing/marketing-cloud/guide/, R = developer.salesforce.com/docs/marketing/marketing-cloud/references/, M = developer.salesforce.com/docs/marketing/mce-mcp/, H = help.salesforce.com/s/articleView?id=

## 1. Auth

| Operation | API | Permission/scope | Sync | Limits | Status | Source |
|---|---|---|---|---|---|---|
| S2S token | POST https://{tenant}.auth.marketingcloudapis.com/v2/token, grant_type=client_credentials, client_id, client_secret, optional scope (subset of package scopes), optional account_id | API Integration, type Server-to-Server | Sync | 20 min token (expires_in=1080), no refresh token, reuse it. Package edits take up to 5 min | GA | D access-token-s2s.html |
| BU targeting | account_id = target MID. Omitted means the BU that created the package | Package needs access to that BU (UNVERIFIED wording) | Sync | | GA | same |
| Tenant endpoints | Token response returns rest_instance_url and soap_instance_url | | | | GA | same |
| Secret lifecycle | 180-day TTL since 25 Mar 2026; staged secrets overlap during rotation | | | Unrotated older secrets expired 30 Sep 2026 | GA | H 005389124&type=1 |
| Platform limits | All REST and SOAP | | | 2,500 sync req/min (token calls excluded), 100 concurrent (soft), 50 objects per sync call, 32,000 per async call, 50M async req/day. Annual: Pro 2M, Corporate 6M, Enterprise 200M. 429 with Retry-After | GA | H mktg.mc_overview_limits_api.htm; D rate-limiting.html |

Scopes take the form Category | Object | Level (D data-access-permissions.html). Data Extensions Read/Write. Email Read/Write/Send. Journeys Read/Write/Execute. Automations Read/Write/Execute. Documents and Images Read/Write. Saved Content Read/Write. Lists and Subscribers Read/Write. Tracking Events Read. API scope strings such as data_extensions_read are UNVERIFIED.

Least-privilege split, three packages. The Reader package holds every Read scope. The Builder package holds the Write scopes with no Send or Execute. The Launcher package holds Email Send, Journeys Execute and Automations Execute, and only the service that launches after a human approves holds its secret.

## 2. Data extensions

| Operation | API | Scope | Sync | Limits | Status | Source |
|---|---|---|---|---|---|---|
| Create, incl. sendable | SOAP Create DataExtension with IsSendable, SendableDataExtensionField, SendableSubscriberField, IsTestable, IsPrimaryKey. REST create path UNVERIFIED | DE Write | Sync | External keys 36 chars or fewer | GA | D dataextension.html |
| Describe | SOAP Retrieve DataExtension and DataExtensionField; REST GET /data/v1/customobjects | DE Read | Sync | | GA | same, MCP GA blog |
| Upsert rows, sync | REST Data Extension Rows (Synchronous); path /hub/v1/dataevents/key:{key}/rowset UNVERIFIED | DE Write | Sync | 50 objects | GA | R index |
| Upsert rows, async | PUT /data/v1/async/dataextensions/key:{key}/rows (UNVERIFIED, third-party only) or SOAP async with RequestID | DE Write | Async | 32,000 objects | GA | D api_best_practices_use_cases_upsert_async.html |
| Bulk load | Bulk Data Ingest API: create job, stage JSON batches, complete, monitor | UNVERIFIED | Async | Release date UNVERIFIED | Documented | D bulkdataingestion.html |
| Data Cloud activation | One BU: lands as a DE. Several BUs: shared DE in the Data 360 subfolder under Shared Data Extensions. One row per unified individual, joined to Subscriber Key. First publish full refresh, incremental after. Switching refresh type creates a new DE. Standard segments refresh 12 or 24 h, rapid segments 1 or 4 h | Data Cloud side | Async | | GA | H sf.c360_a_create_marketing_cloud_activation.htm; H sf.c360_a_activation_publish_types.htm |

## 3. Content Builder

| Operation | API | Scope | Sync | Limits | Status | Source |
|---|---|---|---|---|---|---|
| Create or update asset | POST /asset/v1/content/assets; update by id (method UNVERIFIED) | Email, Saved Content, Documents and Images Write (per-type mapping UNVERIFIED) | Sync | Base64 upload up to 5 MB | GA | D content-api.html |
| Asset types | 208 htmlemail, 207 templatebasedemail, 197 htmlblock, 8 image (28 png, 23 jpg); only assetType.id required | | | | GA | D base-asset-types.html |
| Preview or render | No documented Engagement endpoint; /guide/v1/emails preview is forum-only | | | | UNVERIFIED | D email.html |
| Approvals | POST and GET /hub/v1/approvals-v2; states draft, submitted, reviewed, returned, approved; blocked=true stops sends | ApprovalItem.VIEW, ApprovalItem.CREATEANDEDIT | Sync | No state-transition endpoint found | GA | R mc_rest_approvals/createApprovalItem.html |

## 4. Send setup

| Operation | API | Scope | Sync | Status | Source |
|---|---|---|---|---|---|
| Send classification | SOAP SendClassification Create/Update/Delete (Retrieve implied) | UNVERIFIED | Sync | GA | D sendclassification.html |
| Sender profile | SOAP SenderProfile CRUD | UNVERIFIED | Sync | GA | D senderprofile.html |
| Delivery profile | SOAP DeliveryProfile Create/Update/Delete | UNVERIFIED | Sync | GA | D deliveryprofile |
| Publication lists | SOAP List with ListClassification=PublicationList, plus Publication | Lists and Subscribers Write | Sync | GA | D list.html |
| Test send | SOAP EmailSendDefinition Perform action "test" (IsTestObject, TestEmailAddr); sendable DE needs IsTestable | Email Send plus "Send or Test Send" | Async | GA | D starting_an_email_send_definition_test_send.html |

## 5. Journey Builder

| Operation | API | Scope | Sync | Limits | Status | Source |
|---|---|---|---|---|---|---|
| Create | POST /interaction/v1/interactions (workflowApiVersion 1.0) | Journeys Write | Sync | | GA | R postCreateInteraction.html |
| Update version | PUT /interaction/v1/interactions; modifiedDate must match | Journeys Write | Sync | | GA | R putUpdateInteraction.html |
| API event entry | POST /interaction/v1/eventDefinitions; fire POST /interaction/v1/events or batch POST /interaction/v1/async/events | Journeys Execute (UNVERIFIED) | Both | 100 contacts per async call; one event key serves at most 10 journeys | GA | R enterContactsIntoJourneyInBatches.html |
| Data Cloud entry | No dedicated segment entry source found; use the activated DE with the DE entry source | | | | UNVERIFIED | H mc_jb_data_extension.htm |
| Email activity | EMAILV2; publish creates a triggered send; email needs a profile center link | Journeys Write | | | GA | send-email.htm |
| Waits and splits | Activities in the journey spec; type names UNVERIFIED | | | | GA | D jb-api-specification.html |
| Validate | No standalone endpoint; validation runs during publish | | | | n/a | interaction-operating-states.htm |
| Publish | POST /interaction/v1/interactions/publishAsync/{id}?versionNumber=, poll GET .../publishStatus/{statusId} | Docs say Read; Execute expected | Async | | GA | R postPublishInteractionById.html |
| Pause, resume | POST /interaction/v1/interactions/pause/{id}; body PausedDays (default 14), ExtendWaitEndDates, RetainContactInjectionWhileJourneyPaused; resume .../resume/{id}?versionNumber= | Activate/Stop/Pause/Resume user permission | Sync | Standard journeys only | GA | R JourneyPauseByDefinitionId.html |
| Stop | POST /interaction/v1/interactions/stop/{id}?versionNumber=; ejects every contact in that version | | Sync | | GA | R postStopInteractionById.html |
| Versioning | Publishing a new version unpublishes the old; old version drains | | | | GA | same |

## 6. One-off sends

| Operation | API | Scope | Sync | Limits | Status | Source |
|---|---|---|---|---|---|---|
| Single-send journey | POST /interaction/v1/interactions, definitionType=Quicksend, channel=email, one emailv2 activity, EmailAudience trigger | Journeys Write and Execute | Async | No goals, versions or recurrence | GA | D single-send-journeys.html |
| Email send definition | SOAP EmailSendDefinition Create, then Perform "start" | Email Send | Async | | GA | D emailsenddefinition.html |
| Triggered send | POST /messaging/v1/messageDefinitionSends/key:{key}/send | Email Send | Async | | GA | R mc_rest_messaging |
| Transactional API | /messaging/v1/email/definitions CRUD plus send (path UNVERIFIED) | Email Send | Async | messageKey unique 72 h; 500 definitions per 7 days per BU; no suppression lists; 1,000 req/s single, 250 batched | GA | D transactional-messaging-api.html |

## 7. Automation Studio

| Operation | API | Scope | Sync | Status | Source |
|---|---|---|---|---|---|
| Create automation | SOAP Automation Create (docs recommend SOAP); REST /automation/v1/automations undocumented | Automations Write | Sync | GA (SOAP) | D interacting_with_automation_studio_via_the_web_service_soap_api.htm |
| Run | SOAP Perform "start" | Automations Execute | Async | GA | D perform.html |
| SQL query | SOAP QueryDefinition Perform, poll AsyncActivityStatus; docs say the query must exist from the UI first; REST /automation/v1/queries undocumented | Query Move user permission | Async | GA | D performing_a_query_activity_using_the_soap_web_service_api.html |
| Data extract | SOAP DataExtractActivity Perform "start" (Tracking Extract is one type) | Data Extract Start | Async | GA | D dataextractactivity |
| File transfer | SOAP FileTransferActivity Perform; docs say create in UI, ops table lists Create | File Transfer Start | Async | GA | D filetransferactivity.html |

## 8. Performance data

| Operation | API | Sync | Limits | Status | Source |
|---|---|---|---|---|---|
| Data views | SQL over _Sent, _Open, _Click, _Bounce, _Unsubscribe, _Journey, _JourneyActivity into a DE | Async | 6 months for _Sent, _Open, _Click, _Bounce; not real time; Enterprise-level views exclude send events | GA | H sf.mc_as_data_views.htm |
| SOAP tracking | TrackingEvent and related objects (Tracking Events Read) | Sync | 2,500 rows per call; 730-day retention since Jan 2025 | GA | D trackingevent.html |
| Tracking extract | DataExtractActivity to SFTP | Async | 30-day window noted | GA | H 000355942 |
| Push events | ENS callbacks: EmailSent, EmailNotSent, EmailBounced; Engagement Email Events members UNVERIFIED | Push | At-least-once, HMAC-signed, 3 s ack, 200 subscriptions per callback | GA | D ens-supported-events.html |
| Journey stats | GET /interaction/v1/interactions?extras=stats; no dedicated analytics API | Sync | | GA | R getInteractionCollection.html |
| Data Cloud connector | Email Studio bundle: sends, opens, clicks, bounces, complaints, unsubscribes, Einstein Engagement Scores; plus Journey and Journey Activity streams | Batch | Hourly delta, daily full, first load up to 24 h, 90-day backfill, Enterprise 2.0 accounts only | GA | H sf.c360_a_marketing_cloud_data_sources.htm |
| To BigQuery | Data Cloud BigQuery zero-copy data share via Analytics Hub; fallback extract to SFTP then GCS. Sharing MCE engagement DMOs specifically UNVERIFIED | Batch | | GA connector | developer.salesforce.com/docs/data/data-cloud-int/guide/c360-a-bigquery-connector.html |

## 9. Einstein

| Feature | API access | Status | Source |
|---|---|---|---|
| Engagement Scoring | DE Einstein_MC_Predictive_Scores, weekly update, readable through DE APIs (inference); also flows to Data Cloud via the connector | GA | H sf.mc_anb_einstein_engagement_scoring_data_extension.htm |
| Send Time Optimization | Journey activity; API JSON UNVERIFIED; needs BU provisioning | GA | H sf.marketing_cloud_einstein.htm |
| Engagement Frequency | Frequency Split journey activity; API UNVERIFIED | GA | H sf.mc_anb_eef.htm |
| Content Selection | Einstein Content Selection API (add asset); 2 MB image limit | GA | developer.salesforce.com/docs/marketing/marketing-cloud-einstein/guide/mc-einstein-add-asset |

## 10. MCE MCP Server

| Item | Detail | Status | Source |
|---|---|---|---|
| Endpoint | US https://mai-mce-mcp-cdp1.sfdc-yfeipo.svc.sfdcfc.net/t/{tenantId}/c/{clientId}/api/mcp; EU host uses sfdc-yzvdd4 | GA June 2026 | M guide/mce-mcp-setup.html |
| Auth | API Integration type Public App, MCP OAuth callback, interactive browser login. Rights are package scopes intersected with the user's permissions. No server-to-server mode documented | | M setup |
| Confirmed tools | sfmc_get_data_extensions, sfmc_get_sms_definitions, sfmc_get_sms_definition, sfmc_create_sms_definition, sfmc_create_sms_send_definition, sfmc_send_outbound_sms_message. Tools carry read-only, destructive, async and open-world flags. Journeys are created in Draft | | M references/mce-mcp-tools/mce-mcp-tools-sms.html |
| Write coverage | DE and journey creation confirmed in examples; exact names for create DE, create asset, publish journey, email send UNVERIFIED | | GA blog |
| Size | About 99 tools at GA (secondary); 40 added in Winter '27 (primary); 142 total (secondary) | | |
| Cost | No MCP surcharge; calls count against the annual API limit | | M guide/mce-mcp-considerations.html |

## 11. Platform direction

Marketing Cloud Next is built on Data 360, and Salesforce positions it as the future of the portfolio (salesforceben, 18 Aug 2026). No end-of-sale or end-of-life notice for Engagement was found; it still receives modest updates. At Dreamforce (15 to 17 Sep 2026) Salesforce restored the "Marketing Cloud" umbrella name and introduced AIforce as an interface layer. salesforce.com/marketing/whats-new lists "Headless Marketing" as GA October '26 without saying whether it covers Engagement or Next. The Headless 360 press release (19 Aug 2026) calls the Marketing Engagement MCP Server GA across journeys, campaigns, DEs and content.

Implication for the build: Engagement REST and SOAP remain supported. Keep the agent tool layer behind adapters so a later move to Next or Data 360 swaps the backing APIs without rewriting agents.

## Not possible via API, or not documented

- Standalone journey validation; validation happens only inside publish.
- Rendered preview of Content Builder emails with subscriber data; the documented check is a SOAP test send.
- Approval state transitions in Content Builder approvals.
- Creating query or file-transfer activities through documented REST; SOAP docs say create them in the UI first.
- A Data Cloud segment entry source as its own API object; use a DE entry.
- Configuring Einstein STO, EEF or Engagement Scoring (UNVERIFIED, likely UI only).
- Pausing single-send or transactional journeys.
- Using the MCE MCP Server with a server-to-server token.

## Changes from July to October 2026

- Winter '27 release notes (19 Aug 2026, upgrades 4 Sep, 2 Oct, 9 Oct) add 40 MCE MCP tools: Automation Studio activities, campaigns, Content Builder folders, bulk upsert, DE query, contact erase, email tracking events.
- Unrotated client secrets expired 30 Sep 2026. Winter '27 adds a client-secret dashboard and auto-revokes compromised secrets.
- Winter '27 adds guided Salesforce Go setup for connecting MCE to Data 360.
- Headless 360 press release (19 Aug 2026) and Dreamforce: "Headless Marketing" listed GA October '26; Campaign Agent (Marketing Cloud Next) GA October 2026.
