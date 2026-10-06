param(
    [string]$Environment = "develop",    # develop | test | prod
    [string]$ProjectName = "handseller"
)
$ErrorActionPreference = "Stop"

function Check($what) {
    if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE)" }
}

if ($Environment -notmatch '^(develop|test|prod)$') {
    throw "Invalid environment '$Environment' (use develop, test or prod)"
}

$Root = Split-Path $PSScriptRoot -Parent
Write-Host "Deploying $ProjectName to $Environment ..." -ForegroundColor Green

# Secrets for THIS environment (git-ignored). Falls back to secrets.auto.tfvars.
$SecretsFile = Join-Path $Root "terraform\secrets.$Environment.tfvars"
if (-not (Test-Path $SecretsFile) -and -not (Test-Path (Join-Path $Root "terraform\secrets.auto.tfvars"))) {
    throw "Missing terraform\secrets.$Environment.tfvars (copy terraform\secrets.auto.tfvars.example)"
}

# 1. Build Lambda package
Set-Location $Root
Write-Host "Building Lambda package..." -ForegroundColor Yellow
python aws/build_lambda.py
Check "Lambda build"

# 2. Terraform workspace & apply
Set-Location (Join-Path $Root "terraform")
$AccountId = aws sts get-caller-identity --query Account --output text
Check "sts get-caller-identity"
$AwsRegion = if ($env:DEFAULT_AWS_REGION) { $env:DEFAULT_AWS_REGION } else { "eu-north-1" }
terraform init -input=false -reconfigure `
    "-backend-config=bucket=$ProjectName-terraform-state-$AccountId" `
    "-backend-config=key=terraform.tfstate" `
    "-backend-config=region=$AwsRegion" `
    "-backend-config=use_lockfile=true" `
    "-backend-config=encrypt=true"
Check "terraform init"

$existing = terraform workspace list | Out-String
if ($existing -match "(?m)^\s*\*?\s*$Environment\s*$") {
    terraform workspace select $Environment
} else {
    terraform workspace new $Environment
}
Check "terraform workspace"

$tfArgs = @("apply", "-var=project_name=$ProjectName", "-var=environment=$Environment", "-auto-approve")
if ($Environment -eq "prod" -and (Test-Path "prod.tfvars")) { $tfArgs += "-var-file=prod.tfvars" }
if (Test-Path $SecretsFile) { $tfArgs += "-var-file=$SecretsFile" }
terraform @tfArgs
Check "terraform apply"

$FrontendBucket = terraform output -raw s3_frontend_bucket
$DistId         = terraform output -raw cloudfront_distribution_id
$CfUrl          = terraform output -raw cloudfront_url
$InngestUrl     = terraform output -raw inngest_url

# 3. Build + deploy frontend (static export, same-origin /api via CloudFront)
Set-Location $Root
Write-Host "Building frontend..." -ForegroundColor Yellow
npm install
Check "npm install"
$env:NEXT_EXPORT = "1"
npm run build
Check "npm run build"
aws s3 sync .\out "s3://$FrontendBucket/" --delete
Check "s3 sync"

# 4. Clear CloudFront cache so the new frontend shows immediately
aws cloudfront create-invalidation --distribution-id $DistId --paths "/*" | Out-Null
Check "cloudfront invalidation"

Write-Host "`nDeployment complete!" -ForegroundColor Green
Write-Host "App URL     : $CfUrl" -ForegroundColor Cyan
Write-Host "Inngest URL : $InngestUrl" -ForegroundColor Cyan
