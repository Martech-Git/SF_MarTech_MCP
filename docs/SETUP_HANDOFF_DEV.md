# Dev setup handoff for Kirti

Version 1.0. Date 2026-10-19. What to set up for sf-mcp in dev, and exactly what to send back so the build can continue.

Three parts, in this order. Part A is a security check on the existing prototype VM and is separate from sf-mcp. Part B deploys sf-mcp to dev (milestones 1 and 2). Part C prepares read-only Salesforce access for milestone 3. Each part ends with a "Send back" table.

## Rules for every part

- Never put a secret in chat, email, a ticket, a PR or a commit. That covers Salesforce client secrets, sf-mcp client API keys and the key pepper. Secrets go straight into Secret Manager; share only the secret's name.
- Use synthetic or test data in the SFMC sandbox BU and the Data 360 test data space. No real subscriber data in dev.
- Grant Secret Manager access per secret, never at project level. Never run anything as the default compute service account.
- Nothing from the existing Go backend's SFMC code is needed. Part C sets up fresh, least-privilege integrations.

## Part A. Prototype VM exposure check (urgent, about 15 minutes)

The VM snapshot shows MySQL published on port 3306 on all interfaces, and a firewall rule that allows tcp 3306. Ports 3000 and 8002 are published the same way. The snapshot does not include source ranges, so it is unknown who can reach them.

1. List the rules with their source ranges:

```bash
gcloud compute firewall-rules list --project=digital-marketing-twin \
  --format="table(name,sourceRanges.list(),allowed[].map().firewall_rule().list(),targetTags.list())"
```

2. If `allow-mysql-private-digitalmarketingtwin` includes `0.0.0.0/0`, or any range outside your own networks, restrict it now. The containers reach MySQL over the Compose network, so the app does not need 3306 open on the VM at all:

```bash
gcloud compute firewall-rules update allow-mysql-private-digitalmarketingtwin \
  --project=digital-marketing-twin --source-ranges=10.10.0.0/24
```

Use the subnet's real range if it differs (`gcloud compute networks subnets describe digitalmarketingtwin-subnet --region=us-east1 --format='value(ipCidrRange)'`).

3. Apply the same review to `allow-app-ports-digitalmarketingtwin` (3000, 8000 to 8002) and the five SSH rules. IAP SSH only needs `35.235.240.0/20`.

4. When the prototype is next touched: move `server.key` out of the Go source directory, and change the Compose mapping for MySQL from `3306:3306` to `127.0.0.1:3306:3306` or remove it.

Send back:

| Item | Example |
|---|---|
| Output of step 1 | The table, pasted as text |
| What you changed | "3306 restricted to 10.10.0.0/24" |

## Part B. Deploy sf-mcp to dev (milestones 1 and 2)

The full command-by-command guide is `docs/DEPLOY_M1_M2.md` in this repo. This part lists the decisions to make first and the results to send back.

### B1. Decide before starting

| Decision | Proposed | Your call |
|---|---|---|
| Dev GCP project | `digital-marketing-twin` | Keep, or name a new project |
| Region | `us-east1` | Keep, or change |
| Hostname for the load balancer | for example `sfmcp-dev.<your domain>` | Needs a DNS record you control |
| Google group for platform admins | for example `sfmcp-admins@nagarro.com`, holding you and Ankit | Needs to exist before step 8 of the guide |

### B2. Steps

1. Ankit merges the PR from branch `m1-m2-skeleton-auth` into `main`.
2. Create branch `dev` from `main`. Cloud Build deploys from `dev`.
3. Follow `docs/DEPLOY_M1_M2.md` sections 1 to 11 in order.
4. Issue a key on `https://<hostname>/admin` for client `build-team-claude-code` and hand it to Ankit in person or through a password manager. Ankit sets it as `SFMCP_API_KEY` on his machine. It never goes into chat.
5. Run the checks in section 11 of the guide.

If the first Cloud Build run fails, send the failing step's name and the last 50 lines of its log. Build logs hold no secrets.

### B3. Send back

| Item | How to get it |
|---|---|
| Project ID and region used | |
| Hostname | |
| First Cloud Build result | Pass, or the failing step and log tail |
| Revision image reference | `gcloud run services describe sf-mcp --region=us-east1 --format='value(spec.template.spec.containers[0].image)'` (should end in `@sha256:...`) |
| `/healthz` response | `curl -s https://<hostname>/healthz` |
| IAP audience value set in the trigger | `/projects/<number>/global/backendServices/<id>` |
| Admin page check | You and Ankit get in; someone outside the group gets 403 |
| Source IP check | Call `/mcp` once with a wrong key from a machine whose public IP you know. In Logs Explorer, find the `auth failure` entry from logger `sf_mcp.security` and compare its `source_ip` with that IP. Send "match" or both values |
| Audit routing | After a few calls, the `sfmcp_audit` dataset in BigQuery holds a table with rows, and the `sfmcp-audit` log bucket shows `sfmcp.audit.tool` entries |
| Retention lock | Confirm the bucket is not locked yet; it gets locked only after legal confirms the audit retention period |

## Part C. Salesforce prep for milestone 3 (read-only)

Milestone 3 builds the read tools. It needs one read-only SFMC integration, one read-only Data 360 integration, and a few test objects in the sandbox. The write integrations wait for milestones 4 and 5, so no write credential exists yet.

### C1. SFMC reader package (sandbox BU)

In SFMC: Setup, Platform Tools, Apps, Installed Packages, New.

1. Name: `sfmcp-reader-dev`.
2. Add Component, API Integration, Server-to-Server.
3. Scopes, Read only: Data Extensions, Email, Journeys, Automations, Documents and Images, Saved Content, Lists and Subscribers, Tracking Events. Nothing with Write, Send or Execute.
4. Access: the sandbox business unit only.
5. Note the client secret expiry date (SFMC expires secrets after 180 days).

Store the two secrets without leaving them in shell history (paste the value, press Enter, then Ctrl-D):

```bash
for name in sfmc-reader-client-id sfmc-reader-client-secret; do
  gcloud secrets create "$name" --replication-policy=user-managed --locations=us-east1
  echo "Paste $name, then Enter, then Ctrl-D:"
  gcloud secrets versions add "$name" --data-file=-
  gcloud secrets add-iam-policy-binding "$name" \
    --member="serviceAccount:sf-mcp-run@<project>.iam.gserviceaccount.com" \
    --role=roles/secretmanager.secretAccessor
done
```

### C2. Data 360 reader app

In Salesforce Setup for the Data 360 org.

1. Create an integration user, for example `sfmcp-d360-reader`, with read-only Data 360 access (the standard Data Cloud User permission set, or your org's closest read-only equivalent). No manage or admin permission sets.
2. External Client App Manager, New: name `sfmcp-d360-reader-dev`. Enable OAuth with scopes `api`, `cdp_api` and `cdp_query_api`. The callback URL can be a placeholder such as `https://localhost/callback`.
3. Enable the Client Credentials Flow and set the Run As user to the integration user from step 1.
4. Leave "Issue JWT-based access tokens for named users" switched off.
5. Store the consumer key and secret the same way as C1, as `d360-reader-client-id` and `d360-reader-client-secret`, with the same per-secret binding.

### C3. Test objects in the sandbox

Synthetic data only.

| Object | What to create |
|---|---|
| Data extensions | One or two with 20 to 50 synthetic rows, one of them sendable. Include an email column with addresses on a domain you control, so masking can be checked |
| Content Builder | One folder for drafts, and one existing email or template inside it |
| Journey | One draft journey, never activated |
| Automation | One existing automation, for status reads only |
| Data 360 | The data space name, one segment (any size), and one DMO with test profiles |

### C4. Network question

Does either org restrict API access by source IP (SFMC IP allowlisting, or Login IP Ranges on the Data 360 integration user's profile)? If yes, sf-mcp needs a static egress IP through Cloud NAT before milestone 3, and the guide gains a section for it.

### C5. Send back

Non-secret values only. These go into `policy/` and the Cloud Run config by PR.

| Item | Example |
|---|---|
| SFMC tenant subdomain | The `<subdomain>` in `https://<subdomain>.auth.marketingcloudapis.com` |
| Sandbox BU MID | Digits |
| Reader package scopes as created | Screenshot of the component page, with the secret area cropped out |
| Client secret expiry date | |
| Data 360 My Domain URL | `https://<domain>.my.salesforce.com` |
| Data 360 org type | Production or sandbox |
| Data space name | `default` or yours |
| Integration user's permission sets | Names |
| Secret names created | The four names from C1 and C2, no values |
| Data extension external keys | For the C3 data extensions |
| Content Builder folder ID and asset ID | |
| Draft journey ID or key | |
| Automation ID or key | |
| Segment API name and DMO API name | |
| IP restriction answer | Yes or no, with the egress IP if one already exists |

## What happens next

- Part B results: any fix the first deploy needs lands as a PR into `dev`.
- Part C values: milestone 3 starts. Its first task is a read-only check script you run in Cloud Shell with the reader secrets. It prints status codes and response field names, never values, and confirms the API details marked UNVERIFIED in `docs/research/` before the read tools depend on them.
