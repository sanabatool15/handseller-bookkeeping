param(
    [Parameter(Mandatory=$true)]
    [string]$Environment,
    [string]$ProjectName = "handseller"
)
$ErrorActionPreference = "Stop"

function Check($what) {
    if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE)" }
}

if ($Environment -notmatch '^(dev|test|prod)$') {
    throw "Invalid environment '$Environment' (use dev, test or prod)"
}

$Root = Split-Path $PSScriptRoot -Parent
Write-Host "Preparing to destroy $ProjectName-$Environment ..." -ForegroundColor Yellow
Set-Location (Join-Path $Root "terraform")

$existing = terraform workspace list | Out-String
if ($existing -notmatch "(?m)^\s*\*?\s*$Environment\s*$") {
    Write-Host "Workspace '$Environment' does not exist. Available:" -ForegroundColor Red
    terraform workspace list
    exit 1
}
terraform workspace select $Environment
Check "terraform workspace"

# Terraform reads the Lambda zip even when destroying; use a placeholder if missing
$Zip = Join-Path $Root "lambda-deployment.zip"
if (-not (Test-Path $Zip)) { New-Item -ItemType File -Path $Zip | Out-Null }

# S3 buckets must be empty before they can be deleted
$AccountId = aws sts get-caller-identity --query Account --output text
Check "sts get-caller-identity"
$FrontendBucket = "$ProjectName-$Environment-frontend-$AccountId"
Write-Host "Emptying $FrontendBucket ..." -ForegroundColor Yellow
aws s3 rm "s3://$FrontendBucket" --recursive 2>$null

$SecretsFile = Join-Path $Root "terraform\secrets.$Environment.tfvars"
$tfArgs = @("destroy", "-var=project_name=$ProjectName", "-var=environment=$Environment", "-auto-approve")
if ($Environment -eq "prod" -and (Test-Path "prod.tfvars")) { $tfArgs += "-var-file=prod.tfvars" }
if (Test-Path $SecretsFile) { $tfArgs += "-var-file=$SecretsFile" }
terraform @tfArgs
Check "terraform destroy"

Write-Host "`nInfrastructure for $Environment destroyed." -ForegroundColor Green
Write-Host "To remove the workspace too:" -ForegroundColor Cyan
Write-Host "  terraform workspace select default"
Write-Host "  terraform workspace delete $Environment"
