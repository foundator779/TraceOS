# TraceOS submission evidence manifest

Verified on 2026-08-27 in Google Cloud project `traceos-506713` (project number `1060372410958`). This manifest contains identifiers and reproduction steps only; it intentionally excludes credentials and private raw evidence.

| Proof | Status | Resource or verification path |
|---|---|---|
| Hosted application | VERIFIED | `https://traceos-1060372410958.us-central1.run.app`, revision `traceos-00045-ggc` |
| Cloud Run limits | VERIFIED | Service `traceos`, region `us-central1`, min 0 / max 1, 1 vCPU, 512 MiB |
| Cloud Audit sink | VERIFIED | Sink `traceos-audit-evidence` -> topic `traceos-audit-evidence` |
| Authenticated Pub/Sub push | VERIFIED | Subscription `traceos-audit-evidence-push`; OIDC service account `traceos-pubsub-push@traceos-506713.iam.gserviceaccount.com` |
| Live evidence in TraceOS | VERIFIED | CASE-042 contains deterministic `EVID-GCP-PUSH-<hash>` records with preserved external event IDs and `authenticated_push=true` |
| Private image storage | VERIFIED | `gs://traceos-506713-traceos-evidence`; public access prevention, uniform access, versioning, 60-day lifecycle |
| Gemini image analysis | VERIFIED | `EVID-IMG-001`, SHA-256 `4f7952cf76a8991e82209a8c0ed7195608bfc8609ae22ce733075ddc6d584318`, model `gemini-2.5-flash` |
| Independent visual correlation | VERIFIED | `OBS-VIS-001` plus a `VERIFIED_CORRELATION` result in CASE-042 |
| Gemini report generation | VERIFIED | `RPT-001`, model `gemini-3.7-flash`, generated `2026-08-26T14:35:37.028549Z` |
| Managed Agent Runtime | VERIFIED | `projects/1060372410958/locations/northamerica-northeast1/reasoningEngines/4881831627325440000` |
| Memory resume | VERIFIED | CASE-042 generation 2 has `MEMORY_READ`, later-evidence verification, and a regenerated report |
| Agent Gateway resource | CONFIGURED ONLY | `projects/traceos-506713/locations/northamerica-northeast1/agentGateways/traceos-egress`; no managed authorization-policy deny/allow claim |
| Managed Model Armor | UNAVAILABLE | Template creation returned `PERMISSION_DENIED`; application reports `LOCAL_FALLBACK` |
| Security Command Center | NOT CONNECTED | Intentionally displayed as `NOT_CONNECTED` |
| Architecture diagram | READY | `docs/architecture.png` (2000 × 1200 submission asset); editable source in `docs/architecture.svg` |
| Demo script | READY | `docs/demo-script.md`; target duration 3:58 |
| Gemma cross-model verifier | VERIFIED | `gemma-4-26b-a4b-it-maas`; verdict `361ff6bb-19da-4e70-bd6c-f739faed18ba`, `SUPPORTED` at `2026-08-28T13:48:12Z` |
| Veo training reconstruction | VERIFIED | `veo-3.1-fast-generate-001`; operation `081d0e8c-78ad-4ca9-b370-c4d234060a5f`, SHA-256 `c889c73ffbe5b5ea81cf26b30c9b8e3ca24c4a326080ab62392d44bbcbff0e66` |
| Lyria tabletop audio | VERIFIED | `lyria-3-clip-preview`; interaction `BJWRauuwD4q85usP2abBqQM`, SHA-256 `dca2a18288defb3456f782460b2e984899d249a1d8cb438fb14bc82e9c590b9f` |
| Training artifact storage | VERIFIED | `gs://traceos-506713-traceos-training`; public access prevention, uniform access, versioning, 60-day lifecycle |
| Training cost ledger | VERIFIED | CASE-042 pack `TRAIN-80EF642A49F5`; conservative estimated total `$0.442`, below the configured `$1` pack breaker and `$5` project limit |

## Reproduction commands

```powershell
$base = "https://traceos-1060372410958.us-central1.run.app"
Invoke-RestMethod "$base/api/v1/healthz"
Invoke-WebRequest -Method Post "$base/api/v1/demo/start"
Invoke-RestMethod "$base/api/v1/cases/CASE-042/replay"
Invoke-RestMethod "$base/api/v1/integrations"
Invoke-RestMethod "$base/api/v1/system/model-integrations"
Invoke-RestMethod "$base/api/v1/system/security-controls"
# After a private, successful generation:
Invoke-RestMethod "$base/api/v1/cases/CASE-042/training-pack"
```

Google Cloud resource verification:

```powershell
gcloud run services describe traceos --project traceos-506713 --region us-central1
gcloud logging sinks describe traceos-audit-evidence --project traceos-506713
gcloud pubsub subscriptions describe traceos-audit-evidence-push --project traceos-506713
gcloud storage buckets describe gs://traceos-506713-traceos-evidence
gcloud storage buckets describe gs://traceos-506713-traceos-training
gcloud pubsub subscriptions describe traceos-training-pack-push --project traceos-506713
gcloud network-services agent-gateways describe traceos-egress --project traceos-506713 --location northamerica-northeast1
```

## Limitations that must remain visible

- The managed Gateway resource exists, but its IAP authorization extension could not be installed with the available non-interactive Cloud SDK. The deny/allow shown in the case is the application policy fallback.
- The active account cannot create the managed Model Armor template. The local fail-closed detector is useful product behavior, but it is not managed Model Armor proof.
- Synthetic identity, endpoint, DNS, browser, text, image, and day-eight records are labeled `DEMO_SYNTHETIC`. Only authenticated Cloud Audit records are labeled live.
- The Devpost entry exists and is managed separately; public video, article, and social links must be verified in the entry before the deadline.
- Gemma, Veo, and Lyria are now supported by real invocation identifiers and outputs. Preserve the Training screen, Cloud logs, and hashes in the final video so the three additional-model claims remain independently verifiable.
