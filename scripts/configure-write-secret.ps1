param(
  [string]$ProjectId = "traceos-506713",
  [string]$Region = "us-central1",
  [string]$Service = "traceos",
  [switch]$Rotate
)
$ErrorActionPreference = "Stop"

$secretId = "traceos-api-key"
$runtimeAccount = "traceos-runtime@$ProjectId.iam.gserviceaccount.com"
gcloud services enable secretmanager.googleapis.com --project $ProjectId --quiet

$secret = gcloud secrets describe $secretId --project $ProjectId --format="value(name)" 2>$null
if (-not $secret) {
  gcloud secrets create $secretId --project $ProjectId --replication-policy automatic --quiet
}
if (-not $secret -or $Rotate.IsPresent) {
  $bytes = New-Object byte[] 32
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
  $value = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
  $temporarySecretFile = [System.IO.Path]::GetTempFileName()
  try {
    [System.IO.File]::WriteAllText($temporarySecretFile, $value)
    gcloud secrets versions add $secretId --project $ProjectId --data-file=$temporarySecretFile --quiet | Out-Null
  } finally {
    $value = $null
    $bytes = $null
    Remove-Item -LiteralPath $temporarySecretFile -Force
  }
}

gcloud secrets add-iam-policy-binding $secretId --project $ProjectId `
  --member "serviceAccount:$runtimeAccount" --role roles/secretmanager.secretAccessor --quiet | Out-Null
gcloud run services update $Service --project $ProjectId --region $Region `
  --update-secrets "TRACEOS_API_KEY=${secretId}:latest" --quiet | Out-Null

Write-Output "Protected TraceOS write endpoints with Secret Manager secret $secretId."
