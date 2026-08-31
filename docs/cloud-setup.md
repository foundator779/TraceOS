# Google Cloud setup

## Cost boundary

The recommended public demo is deliberately bounded:

- Cloud Run: minimum instances `0`, maximum instances `1`, 1 CPU, 512 MiB;
- Firestore: one small document per case plus idempotency keys;
- Cloud Logging query: one recent Admin Activity entry per demo run;
- no deployed API key; Gemini uses the Cloud Run service identity on Vertex AI;
- no always-on worker and no minimum-capacity database;
- Gemini is invoked for one cached synthetic image and final verified-report prose, not for every runtime event;
- public demo starts are persisted and limited to 20 per UTC day.
- bonus-model generation is disabled by default, API-key protected, cached by report hash, limited to one live pack, and blocked above an estimated USD 1.

Create a Google Cloud billing budget capped at USD 5 with alerts at 50%, 80%, and 100%. A budget alerts; it does not automatically disable billing, so also retain the Cloud Run maximum-instance limit.

## Least-privilege identities

`traceos-runtime` receives:

- `roles/datastore.user` — application state;
- `roles/logging.viewer` — scoped Cloud Audit Log read;
- `roles/logging.logWriter` — application telemetry;
- `roles/aiplatform.user` — Gemini on Vertex AI;
- `roles/modelarmor.user` only when the managed safety adapter is enabled.

Do not grant Owner or Editor.

## Cloud Audit Logs

The on-demand connector uses the official Cloud Logging client and a bounded query:

```text
logName:"cloudaudit.googleapis.com%2Factivity"
timestamp >= now - 30 days
order: newest first
limit: 1
```

A record is labeled `GOOGLE_CLOUD_LIVE` only when the authenticated query returns an actual `LogEntry`. Its project, resource, log name, insert ID, timestamp, and payload hash are retained.

For near-real-time ingestion, apply `infra/main.tf`. It creates:

```text
Cloud Audit Logs → filtered Logging sink → traceos-audit-evidence Pub/Sub topic
```

`scripts/configure-cloud-evidence.ps1` creates an authenticated push subscription. The endpoint verifies the Google-signed OIDC token, expected audience, verified email, and exact push service-account identity before registering a record as live. Deliveries are deduplicated by Pub/Sub message ID.

## Security Command Center

The API accepts SCC-shaped Pub/Sub envelopes at `POST /api/v1/ingest/scc`, but deliberately quarantines them until authenticated push and an SCC NotificationConfig are verified. When SCC is available:

1. enable Security Command Center at the permitted project or organization scope;
2. create `traceos-scc-findings`;
3. configure a narrow active HIGH/CRITICAL finding notification;
4. require authenticated Cloud Run invocation by the Pub/Sub service agent;
5. preserve the finding resource name, source, severity, asset, event time, and hash;
6. capture the source finding and matching TraceOS record for submission evidence.

If SCC cannot be enabled, keep the UI status `NOT_CONNECTED` and use Cloud Audit Logs as the honest live enterprise connector.

## Agent Runtime / Memory Bank

The deployable ADK application is `backend/agents/agent.py`. It has one coordinator and ten bounded forensic specialists. `scripts/deploy-agent-platform.py` deploys it through the Gemini Enterprise Agent Runtime API with an Agent Identity, Vertex AI session and memory operations, Agent Runtime tracing enabled, zero minimum instances, and a one-instance maximum.

The active TraceOS deployment is:

```text
project: traceos-506713
Agent Runtime location: northamerica-northeast1
resource: projects/1060372410958/locations/northamerica-northeast1/reasoningEngines/4881831627325440000
model: gemini-3.5-flash
staging bucket: gs://traceos-506713-agent-platform-ca
```

Deploy a replacement only when required:

```powershell
python scripts/deploy-agent-platform.py
```

After deployment, set the returned values on the Cloud Run control plane:

```text
GOOGLE_CLOUD_AGENT_ENGINE_ID=...
GOOGLE_CLOUD_AGENT_ENGINE_LOCATION=northamerica-northeast1
GOOGLE_CLOUD_PROJECT=traceos-506713
GOOGLE_CLOUD_LOCATION=us-central1
GEMINI_LOCATION=global
```

The runtime was exercised with a live streamed ADK query and an Agent Runtime session. The custom Fleet and Memory screens remain product views; use Agent Runtime resource and session/memory operations as managed-platform evidence.

## Model Armor

Create a regional Model Armor template, grant the runtime identity `roles/modelarmor.user`, then set:

```text
ENABLE_MODEL_ARMOR=true
MODEL_ARMOR_TEMPLATE_ID=traceos-evidence
```

Until a managed response succeeds, TraceOS labels the local fail-closed detector `LOCAL_FAIL_CLOSED`; it never presents that fallback as managed Model Armor proof.

The current project returned `PERMISSION_DENIED` during template creation, so the hosted service deliberately has `ENABLE_MODEL_ARMOR=false` and reports `LOCAL_FALLBACK`.

## Image evidence

The production deployment uses `gs://traceos-506713-traceos-evidence` with public access prevention, uniform bucket access, versioning, and a 60-day lifecycle. Arbitrary uploads require `X-TraceOS-API-Key`; the public demo action can attach only its bundled, watermarked synthetic fixture.

## Verified training pack and bonus models

The optional branch is strictly downstream of `RPT-001`:

```text
verified report → Gemma challenge → redaction boundary → Pub/Sub worker → Veo + Lyria
```

`scripts/configure-training-pack.ps1` creates a separate private, versioned, 60-day training bucket plus an OIDC-authenticated Pub/Sub push worker. Running the script without switches performs zero model invocations and leaves every bonus model disabled:

```powershell
.\scripts\configure-training-pack.ps1 -ProjectId traceos-506713 -Region us-central1 -ServiceUrl $serviceUrl
```

After confirming access and quota, opt in explicitly:

```powershell
.\scripts\configure-training-pack.ps1 -ProjectId traceos-506713 -Region us-central1 -ServiceUrl $serviceUrl -EnableGemma -EnableVeo -EnableLyria
```

The private write endpoint then creates at most one live pack:

```text
POST /api/v1/cases/CASE-042/training-pack
X-TraceOS-API-Key: <private value>
```

Gemma receives structured verified findings and evidence identifiers, never raw evidence. `UNSUPPORTED` routes to human review. Veo and Lyria failures produce `ARTIFACT_UNAVAILABLE`; the investigation and report remain complete. Media is stamped `SYNTHETIC TRAINING MATERIAL — NOT EVIDENCE`, stored outside the evidence bucket, hashed, and served through an integrity-checking endpoint.

## Agent Gateway

The resource `projects/traceos-506713/locations/northamerica-northeast1/agentGateways/traceos-egress` is provisioned and linked to Agent Registry. Its managed authorization extension was unavailable in the installed non-interactive Cloud SDK, so the hosted API reports `CONFIGURED` with `managed_claim=false`. Set `AGENT_GATEWAY_STATUS=CONNECTED` only after a managed deny and allow have been captured.
