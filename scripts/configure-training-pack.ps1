param(
  [string]$ProjectId = "traceos-506713",
  [string]$Region = "us-central1",
  [Parameter(Mandatory = $true)][string]$ServiceUrl,
  [switch]$EnableGemma,
  [switch]$EnableVeo,
  [switch]$EnableLyria
)
$ErrorActionPreference = "Stop"

# This script provisions only serverless, scale-to-zero resources. It never invokes
# a model. Model flags opt in to future API calls; the application still enforces a
# $1 pack budget, one live run, report-hash idempotency, and an API key.
$trainingBucket = "$ProjectId-traceos-training"
$topic = "traceos-training-pack"
$subscription = "traceos-training-pack-push"
$pushAccount = "traceos-pubsub-push@$ProjectId.iam.gserviceaccount.com"
$runtimeAccount = "traceos-runtime@$ProjectId.iam.gserviceaccount.com"
$audience = "$ServiceUrl/api/v1/internal/training-pack/jobs"
$lifecycle = Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..")).Path "infra\storage-lifecycle.json"

if (-not (gcloud storage buckets list --project $ProjectId --filter="name=$trainingBucket" --format="value(name)")) {
  gcloud storage buckets create "gs://$trainingBucket" --project $ProjectId --location $Region --uniform-bucket-level-access --public-access-prevention
}
gcloud storage buckets update "gs://$trainingBucket" --versioning --lifecycle-file $lifecycle --quiet
gcloud storage buckets add-iam-policy-binding "gs://$trainingBucket" --member "serviceAccount:$runtimeAccount" --role roles/storage.objectAdmin --quiet | Out-Null

if (-not (gcloud pubsub topics list --project $ProjectId --filter="name:$topic" --format="value(name)")) {
  gcloud pubsub topics create $topic --project $ProjectId
}
gcloud pubsub topics add-iam-policy-binding $topic --project $ProjectId --member "serviceAccount:$runtimeAccount" --role roles/pubsub.publisher --quiet | Out-Null
gcloud run services add-iam-policy-binding traceos --project $ProjectId --region $Region --member "serviceAccount:$pushAccount" --role roles/run.invoker --quiet | Out-Null

if (gcloud pubsub subscriptions list --project $ProjectId --filter="name:$subscription" --format="value(name)") {
  gcloud pubsub subscriptions update $subscription --project $ProjectId --push-endpoint $audience --push-auth-service-account $pushAccount --push-auth-token-audience $audience --ack-deadline 30
} else {
  gcloud pubsub subscriptions create $subscription --project $ProjectId --topic $topic --push-endpoint $audience --push-auth-service-account $pushAccount --push-auth-token-audience $audience --ack-deadline 30 --expiration-period never
}

$gemmaEnabled = $EnableGemma.IsPresent.ToString().ToLowerInvariant()
$veoEnabled = $EnableVeo.IsPresent.ToString().ToLowerInvariant()
$lyriaEnabled = $EnableLyria.IsPresent.ToString().ToLowerInvariant()
gcloud run services update traceos --project $ProjectId --region $Region `
  --update-env-vars "TRAINING_OUTPUT_BUCKET=$trainingBucket,TRAINING_PUBSUB_TOPIC=projects/$ProjectId/topics/$topic,TRAINING_PUBSUB_AUDIENCE=$audience,TRAINING_WORKER_SERVICE_ACCOUNT=$pushAccount,TRAINING_BUDGET_USD=1.00,TRAINING_MAX_LIVE_RUNS=1,TRAINING_MAX_ARTIFACT_RETRIES=2,GEMMA_VERIFIER_MODEL=gemma-4-26b-a4b-it-maas,VEO_TRAINING_MODEL=veo-3.1-fast-generate-001,LYRIA_TRAINING_MODEL=lyria-3-clip-preview,ENABLE_GEMMA_VERIFIER=$gemmaEnabled,ENABLE_VEO_TRAINING=$veoEnabled,ENABLE_LYRIA_TRAINING=$lyriaEnabled" --quiet

[pscustomobject]@{
  TrainingBucket = $trainingBucket
  Topic = $topic
  Subscription = $subscription
  GemmaEnabled = $EnableGemma.IsPresent
  VeoEnabled = $EnableVeo.IsPresent
  LyriaEnabled = $EnableLyria.IsPresent
  ModelInvocationsPerformed = 0
  ConfiguredPackBudgetUsd = 1.00
}
