# Deploying sf-mcp to dev (milestones 1 and 2)

Audience: the engineer who owns GCP setup (Kirti). Run the steps in order; later steps depend on earlier ones. Every command assumes the dev project. Values in angle brackets are yours to fill in.

What gets deployed: one Cloud Run service, `sf-mcp`, behind an external HTTPS load balancer. `/mcp` takes client API keys. `/admin` sits behind IAP for platform admins. `/healthz` is open. Nothing in this release calls Salesforce, so no SFMC or Data 360 credentials are needed yet.

```bash
export PROJECT_ID=<dev project id, SPEC A3 proposes digital-marketing-twin>
export REGION=us-east1
export PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
export DOMAIN=<hostname for the load balancer, for example sfmcp-dev.example.com>
export ADMIN_GROUP=<Google group of platform admins, for example sfmcp-admins@example.com>
gcloud config set project "$PROJECT_ID"
```

## 1. APIs

```bash
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com firestore.googleapis.com iap.googleapis.com compute.googleapis.com \
  cloudtrace.googleapis.com logging.googleapis.com monitoring.googleapis.com iam.googleapis.com
```

## 2. Artifact Registry

```bash
gcloud artifacts repositories create sf-mcp --repository-format=docker --location="$REGION" \
  --description="sf-mcp images"
```

## 3. Service accounts

Two accounts, never the default compute account.

```bash
gcloud iam service-accounts create sf-mcp-run --display-name="sf-mcp runtime"
gcloud iam service-accounts create sf-mcp-build --display-name="sf-mcp Cloud Build"
RUN_SA=sf-mcp-run@$PROJECT_ID.iam.gserviceaccount.com
BUILD_SA=sf-mcp-build@$PROJECT_ID.iam.gserviceaccount.com

for role in roles/datastore.user roles/logging.logWriter roles/cloudtrace.agent roles/monitoring.metricWriter; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$RUN_SA" --role="$role"
done

for role in roles/run.admin roles/artifactregistry.writer roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$BUILD_SA" --role="$role"
done
gcloud iam service-accounts add-iam-policy-binding "$RUN_SA" \
  --member="serviceAccount:$BUILD_SA" --role=roles/iam.serviceAccountUser
```

The build account needs `roles/run.admin` because the deploy sets `--no-invoker-iam-check`. Grant the runtime account no project-level Secret Manager role; step 5 grants one secret only.

## 4. Firestore

A dedicated database named `sf-mcp`, Native mode, in the service's region.

```bash
gcloud firestore databases create --database=sf-mcp --location="$REGION" --type=firestore-native
```

Collections appear on first write: `keys`, `config`, `audit_chain_heads`.

## 5. Key pepper secret

The pepper turns client key secrets into stored HMACs. Generate it once; nobody needs to read it.

```bash
openssl rand -base64 48 | tr -d '\n' | gcloud secrets create sfmcp-key-pepper \
  --replication-policy=user-managed --locations="$REGION" --data-file=-
gcloud secrets add-iam-policy-binding sfmcp-key-pepper \
  --member="serviceAccount:$RUN_SA" --role=roles/secretmanager.secretAccessor
```

Rotating the pepper invalidates every issued key. Treat a rotation as "revoke all keys and reissue".

## 6. Branches and the Cloud Build trigger

1. Create the `dev` branch from `main` in sfmc99/SF_MarTech_MCP once the spec PR is merged.
2. Connect the repo to Cloud Build (2nd gen GitHub connection) in `$REGION`.
3. Create a trigger on pushes to `^dev$` using `cloudbuild.yaml`, running as `$BUILD_SA`, with these substitutions:

| Substitution | Value |
|---|---|
| `_ENV` | `dev` |
| `_REGION` | `us-east1` |
| `_RUN_SA` | `sf-mcp-run@<project>.iam.gserviceaccount.com` |
| `_IAP_AUDIENCE_ADMIN` | Leave the placeholder for the first run; step 9 sets the real value |
| `_MIN_INSTANCES` | `0` in dev |

4. Run the trigger once. The `test` step runs ruff, mypy and pytest; a failure stops the build before any image exists. The deploy step deploys by digest.

The first deploy creates the `sf-mcp` service with ingress limited to internal traffic and the load balancer, so it is not reachable until step 7 exists. The admin page answers 403 until step 9 sets the real IAP audience.

## 7. Load balancer and Cloud Armor

Two serverless NEGs point at the same service, so `/admin` and `/mcp` can sit on different backend services with different IAP settings.

```bash
gcloud compute addresses create sf-mcp-ip --global
gcloud compute ssl-certificates create sf-mcp-cert --domains="$DOMAIN" --global

for name in mcp admin; do
  gcloud compute network-endpoint-groups create sf-mcp-neg-$name --region="$REGION" \
    --network-endpoint-type=serverless --cloud-run-service=sf-mcp
  gcloud compute backend-services create sf-mcp-be-$name --global \
    --load-balancing-scheme=EXTERNAL_MANAGED --protocol=HTTPS
  gcloud compute backend-services add-backend sf-mcp-be-$name --global \
    --network-endpoint-group=sf-mcp-neg-$name --network-endpoint-group-region="$REGION"
done

gcloud compute url-maps create sf-mcp-lb --default-service=sf-mcp-be-mcp --global
gcloud compute url-maps add-path-matcher sf-mcp-lb --global --path-matcher-name=paths \
  --default-service=sf-mcp-be-mcp --path-rules="/admin=sf-mcp-be-admin,/admin/*=sf-mcp-be-admin" \
  --new-hosts="$DOMAIN"
gcloud compute target-https-proxies create sf-mcp-proxy --url-map=sf-mcp-lb --ssl-certificates=sf-mcp-cert --global
gcloud compute forwarding-rules create sf-mcp-https --global --load-balancing-scheme=EXTERNAL_MANAGED \
  --address=sf-mcp-ip --target-https-proxy=sf-mcp-proxy --ports=443
```

Point `$DOMAIN` at the reserved address (`gcloud compute addresses describe sf-mcp-ip --global`). The managed certificate goes active after DNS resolves.

Cloud Armor on the MCP backend: a per-IP rate cap that bans abusive sources, which also covers lockout state that is per instance in the app.

```bash
gcloud compute security-policies create sf-mcp-armor
gcloud compute security-policies rules create 1000 --security-policy=sf-mcp-armor \
  --src-ip-ranges="*" --action=rate-based-ban --rate-limit-threshold-count=300 \
  --rate-limit-threshold-interval-sec=60 --ban-duration-sec=600 --conform-action=allow \
  --exceed-action=deny-429 --enforce-on-key=IP
gcloud compute backend-services update sf-mcp-be-mcp --global --security-policy=sf-mcp-armor
```

## 8. IAP on the admin backend

1. Configure the OAuth consent screen as Internal (APIs and Services, OAuth consent screen), if the project has none.
2. Enable IAP on the admin backend only, and grant the admin group access:

```bash
gcloud iap web enable --resource-type=backend-services --service=sf-mcp-be-admin
gcloud iap web add-iam-policy-binding --resource-type=backend-services --service=sf-mcp-be-admin \
  --member="group:$ADMIN_GROUP" --role=roles/iap.httpsResourceAccessor
```

The app checks a second list too: only emails in `policy/humans.yaml` under `platform_admins` get in. Adding a person means both the group and a policy PR.

## 9. Set the IAP audience and redeploy

```bash
BACKEND_ID=$(gcloud compute backend-services describe sf-mcp-be-admin --global --format='value(id)')
echo "/projects/$PROJECT_NUMBER/global/backendServices/$BACKEND_ID"
```

Put that value in the trigger's `_IAP_AUDIENCE_ADMIN` substitution and run the trigger again.

## 10. Audit routing

Audit events are JSON lines whose `event_type` starts with `sfmcp.audit`. Route them to a dedicated bucket and to BigQuery.

```bash
gcloud logging buckets create sfmcp-audit --location="$REGION" --retention-days=400
gcloud logging sinks create sfmcp-audit-bucket \
  "logging.googleapis.com/projects/$PROJECT_ID/locations/$REGION/buckets/sfmcp-audit" \
  --log-filter='resource.type="cloud_run_revision" AND jsonPayload.event_type=~"^sfmcp\.audit"'
bq --location="$REGION" mk --dataset "$PROJECT_ID:sfmcp_audit"
gcloud logging sinks create sfmcp-audit-bq "bigquery.googleapis.com/projects/$PROJECT_ID/datasets/sfmcp_audit" \
  --log-filter='resource.type="cloud_run_revision" AND jsonPayload.event_type=~"^sfmcp\.audit"' \
  --use-partitioned-tables
```

Grant each sink's writer identity (shown by `gcloud logging sinks describe <sink>`) write access on its destination.

Retention lock is irreversible. Lock the bucket only after legal confirms the period (SPEC A9): `gcloud logging buckets update sfmcp-audit --location="$REGION" --locked`.

## 11. Checks for milestones 1 and 2

| Check | How |
|---|---|
| Deploys by digest from a merge to `dev` | Cloud Run revision image shows `@sha256:` |
| Health | `curl https://$DOMAIN/healthz` returns `{"status":"ok",...}` |
| Traces | A call to `/mcp` shows spans named `sfmcp.tool_call` and `sfmcp.step.*` in Cloud Trace |
| Provenance | Artifact Registry shows build provenance on the image |
| Admin behind IAP | `https://$DOMAIN/admin` asks for Google sign-in; a non-admin gets 403 |
| Key issue | On `/admin`, issue a key for `build-team-claude-code`; the key shows once |
| Client works | In Claude Code: `claude mcp add --transport http sf-mcp https://$DOMAIN/mcp --header "Authorization: Bearer $SFMCP_API_KEY"`, then `/mcp` lists the `health` tool |
| Bad keys refused | A wrong, revoked or expired key gets 401; revocation takes effect within 10 seconds |
| No grants, no tools | A client with no grants in `policy/clients.yaml` sees zero tools |
| Audit lands | The `sfmcp-audit` bucket and `sfmcp_audit` dataset receive `sfmcp.audit.tool` and `sfmcp.audit.admin` events |

One value to confirm on the first deploy: the server reads the caller's address from `X-Forwarded-For` at index -2 (the Google load balancer appends `<client-ip>, <lb-ip>`). Before any client uses a CIDR allowlist instead of `"*"`, confirm the logged address matches the real caller, and adjust `SFMCP_XFF_CLIENT_INDEX` if needed.

## Deferred to milestone 6 (prod)

Binary Authorization enforcement, VPC Service Controls, a prod project with its own secrets and trigger on `main`, a static egress IP through Cloud NAT, and alert policies.
