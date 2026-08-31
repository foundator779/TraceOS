param(
  [string]$ProjectId = "traceos-506713",
  [string]$Region = "us-central1",
  [Parameter(Mandatory = $true)][string]$ServiceUrl
)
$ErrorActionPreference = "Stop"

$topic = "traceos-audit-evidence"
$subscription = "traceos-audit-evidence-push"
$sink = "traceos-audit-evidence"
$pushAccount = "traceos-pubsub-push@$ProjectId.iam.gserviceaccount.com"
$audience = "$ServiceUrl/api/v1/ingest/cloud-audit"

if (-not (gcloud iam service-accounts list --project $ProjectId --filter="email=$pushAccount" --format="value(email)")) {
  gcloud iam service-accounts create traceos-pubsub-push --project $ProjectId --display-name "TraceOS authenticated Pub/Sub push"
}
if (-not (gcloud pubsub topics list --project $ProjectId --filter="name:$topic" --format="value(name)")) {
  gcloud pubsub topics create $topic --project $ProjectId
}
if (-not (gcloud logging sinks list --project $ProjectId --filter="name=$sink" --format="value(name)")) {
  gcloud logging sinks create $sink "pubsub.googleapis.com/projects/$ProjectId/topics/$topic" --project $ProjectId --log-filter='logName:"cloudaudit.googleapis.com%2Factivity"'
}
$writer = gcloud logging sinks describe $sink --project $ProjectId --format="value(writerIdentity)"
gcloud pubsub topics add-iam-policy-binding $topic --project $ProjectId --member $writer --role roles/pubsub.publisher --quiet | Out-Null
gcloud run services add-iam-policy-binding traceos --project $ProjectId --region $Region --member "serviceAccount:$pushAccount" --role roles/run.invoker --quiet | Out-Null

$projectNumber = gcloud projects describe $ProjectId --format="value(projectNumber)"
$pubsubAgent = "service-$projectNumber@gcp-sa-pubsub.iam.gserviceaccount.com"
gcloud projects add-iam-policy-binding $ProjectId --member "serviceAccount:$pubsubAgent" --role roles/iam.serviceAccountTokenCreator --condition=None --quiet | Out-Null

if (gcloud pubsub subscriptions list --project $ProjectId --filter="name:$subscription" --format="value(name)") {
  gcloud pubsub subscriptions update $subscription --project $ProjectId --push-endpoint $audience --push-auth-service-account $pushAccount --push-auth-token-audience $audience --ack-deadline 30
} else {
  gcloud pubsub subscriptions create $subscription --project $ProjectId --topic $topic --push-endpoint $audience --push-auth-service-account $pushAccount --push-auth-token-audience $audience --ack-deadline 30 --expiration-period never
}
gcloud run services update traceos --project $ProjectId --region $Region --update-env-vars "PUBSUB_PUSH_AUDIENCE=$audience,PUBSUB_PUSH_SERVICE_ACCOUNT=$pushAccount" --quiet

# Model Armor is a separate managed proof. Keep the app honest if the preview
# command is unavailable rather than claiming the local fallback is managed.
$template = gcloud model-armor templates list --project $ProjectId --location $Region --filter="name:traceos-evidence" --format="value(name)"
if (-not $template) {
  try {
    gcloud model-armor templates create traceos-evidence --project $ProjectId --location $Region --basic-config-filter-enforcement=enabled --pi-and-jailbreak-filter-settings-enforcement=enabled --pi-and-jailbreak-filter-settings-confidence-level=medium-and-above --malicious-uri-filter-settings-enforcement=enabled --quiet
  } catch {
    Write-Warning "Managed Model Armor template was unavailable; TraceOS will report its local fail-closed fallback honestly."
  }
}
