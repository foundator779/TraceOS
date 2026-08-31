param(
  [string]$ProjectId = "traceos-506713",
  [string]$Location = "northamerica-northeast1"
)
$ErrorActionPreference = "Stop"
$resolvedRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gatewayConfig = Join-Path $resolvedRoot "infra\agent-gateway-egress.yaml"
$extensionConfig = Join-Path $resolvedRoot "infra\agent-gateway-iap-extension.yaml"
$policyConfig = Join-Path $resolvedRoot "infra\agent-gateway-authz-policy.yaml"

gcloud network-services agent-gateways import traceos-egress --source $gatewayConfig --location $Location --project $ProjectId --quiet
gcloud beta service-extensions authz-extensions import traceos-iap-dry-run --source $extensionConfig --location $Location --project $ProjectId --quiet
if ($LASTEXITCODE -eq 0) {
  gcloud network-security authz-policies import traceos-egress-authz --source $policyConfig --location $Location --project $ProjectId --quiet
} else {
  Write-Warning "Gateway created, but the dry-run IAP extension is unavailable in this non-interactive Cloud SDK. Keep AGENT_GATEWAY_STATUS=CONFIGURED until the policy and managed traffic are verified."
}

gcloud network-services agent-gateways describe traceos-egress --location $Location --project $ProjectId --format=json
