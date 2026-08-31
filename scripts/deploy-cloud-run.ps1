param(
  [string]$ProjectId = "traceos-506713",
  [string]$Region = "us-central1",
  [string]$AgentEngineId = "4881831627325440000",
  [string]$AgentEngineLocation = "northamerica-northeast1"
)
$ErrorActionPreference = "Stop"

$resolvedRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$currentProject = gcloud config get-value project 2>$null
if ($currentProject -ne $ProjectId) {
  gcloud config set project $ProjectId | Out-Null
}

$services = @(
  "run.googleapis.com", "cloudbuild.googleapis.com", "artifactregistry.googleapis.com",
  "firestore.googleapis.com", "logging.googleapis.com", "aiplatform.googleapis.com",
  "modelarmor.googleapis.com", "pubsub.googleapis.com", "storage.googleapis.com",
  "secretmanager.googleapis.com"
)
foreach ($service in $services) {
  gcloud services enable $service --project $ProjectId --quiet
}

$serviceAccount = "traceos-runtime@$ProjectId.iam.gserviceaccount.com"
$existingServiceAccount = gcloud iam service-accounts list --project $ProjectId --filter="email=$serviceAccount" --format="value(email)"
if (-not $existingServiceAccount) {
  gcloud iam service-accounts create traceos-runtime --display-name "TraceOS runtime" --project $ProjectId
}
foreach ($role in @("roles/datastore.user", "roles/logging.viewer", "roles/logging.logWriter", "roles/aiplatform.user")) {
  gcloud projects add-iam-policy-binding $ProjectId --member "serviceAccount:$serviceAccount" --role $role --condition=None --quiet | Out-Null
}

$evidenceBucket = "$ProjectId-traceos-evidence"
$trainingBucket = "$ProjectId-traceos-training"
$bucketExists = gcloud storage buckets list --project $ProjectId --filter="name=$evidenceBucket" --format="value(name)"
if (-not $bucketExists) {
  gcloud storage buckets create "gs://$evidenceBucket" --project $ProjectId --location $Region --uniform-bucket-level-access --public-access-prevention
}
gcloud storage buckets update "gs://$evidenceBucket" --versioning --lifecycle-file (Join-Path $resolvedRoot "infra\storage-lifecycle.json") --quiet
gcloud storage buckets add-iam-policy-binding "gs://$evidenceBucket" --member "serviceAccount:$serviceAccount" --role roles/storage.objectAdmin --quiet | Out-Null
if (-not (gcloud storage buckets list --project $ProjectId --filter="name=$trainingBucket" --format="value(name)")) {
  gcloud storage buckets create "gs://$trainingBucket" --project $ProjectId --location $Region --uniform-bucket-level-access --public-access-prevention
}
gcloud storage buckets update "gs://$trainingBucket" --versioning --lifecycle-file (Join-Path $resolvedRoot "infra\storage-lifecycle.json") --quiet
gcloud storage buckets add-iam-policy-binding "gs://$trainingBucket" --member "serviceAccount:$serviceAccount" --role roles/storage.objectAdmin --quiet | Out-Null

$databaseNames = gcloud firestore databases list --project $ProjectId --format="value(name)" 2>$null
if (-not ($databaseNames -match '/databases/\(default\)$')) {
  gcloud firestore databases create --database="(default)" --location=nam5 --type=firestore-native --project $ProjectId --quiet
}

gcloud run deploy traceos --source $resolvedRoot --project $ProjectId --region $Region `
  --allow-unauthenticated --service-account $serviceAccount --min-instances 0 --max-instances 1 `
  --memory 512Mi --cpu 1 --concurrency 40 --timeout 300 `
  --set-env-vars "ENVIRONMENT=production,GOOGLE_CLOUD_PROJECT=$ProjectId,GOOGLE_CLOUD_LOCATION=$Region,TRACEOS_STORE=firestore,ENABLE_CLOUD_CONNECTORS=true,ENABLE_MODEL_ARMOR=false,MODEL_ARMOR_TEMPLATE_ID=traceos-evidence,EVIDENCE_BUCKET=$evidenceBucket,TRAINING_OUTPUT_BUCKET=$trainingBucket,TRAINING_BUDGET_USD=1.00,TRAINING_MAX_LIVE_RUNS=1,ENABLE_GEMMA_VERIFIER=false,ENABLE_VEO_TRAINING=false,ENABLE_LYRIA_TRAINING=false,GEMINI_MODEL=gemini-3.7-flash,GEMINI_VISION_MODEL=gemini-2.5-flash,GEMINI_LOCATION=global,GEMINI_USE_VERTEX=true,GOOGLE_CLOUD_AGENT_ENGINE_ID=$AgentEngineId,GOOGLE_CLOUD_AGENT_ENGINE_LOCATION=$AgentEngineLocation,AGENT_GATEWAY_STATUS=CONFIGURED" --quiet
if ($LASTEXITCODE -ne 0) {
  throw "Cloud Run source build failed; connector and secret configuration were not changed."
}

$serviceUrl = gcloud run services describe traceos --project $ProjectId --region $Region --format="value(status.url)"
& (Join-Path $PSScriptRoot "configure-cloud-evidence.ps1") -ProjectId $ProjectId -Region $Region -ServiceUrl $serviceUrl
& (Join-Path $PSScriptRoot "configure-training-pack.ps1") -ProjectId $ProjectId -Region $Region -ServiceUrl $serviceUrl
& (Join-Path $PSScriptRoot "configure-write-secret.ps1") -ProjectId $ProjectId -Region $Region

$serviceUrl
