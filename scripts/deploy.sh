#!/bin/bash
set -e

ENVIRONMENT=${1:-dev}          # dev | test | prod
PROJECT_NAME=${2:-handseller}

case "$ENVIRONMENT" in dev|test|prod) ;; *) echo "Invalid environment: $ENVIRONMENT"; exit 1;; esac

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
echo "Deploying ${PROJECT_NAME} to ${ENVIRONMENT}..."

SECRETS="$ROOT/terraform/secrets.${ENVIRONMENT}.tfvars"
if [ ! -f "$SECRETS" ] && [ ! -f "$ROOT/terraform/secrets.auto.tfvars" ]; then
  echo "Missing terraform/secrets.${ENVIRONMENT}.tfvars (copy terraform/secrets.auto.tfvars.example)"; exit 1
fi

# 1. Build Lambda package
python aws/build_lambda.py

# 2. Terraform workspace & apply
cd terraform
terraform init -input=false
if terraform workspace list | grep -qE "^\*?\s*${ENVIRONMENT}$"; then
  terraform workspace select "$ENVIRONMENT"
else
  terraform workspace new "$ENVIRONMENT"
fi

ARGS=(-var="project_name=$PROJECT_NAME" -var="environment=$ENVIRONMENT" -auto-approve)
[ "$ENVIRONMENT" = "prod" ] && [ -f prod.tfvars ] && ARGS+=(-var-file=prod.tfvars)
[ -f "$SECRETS" ] && ARGS+=(-var-file="$SECRETS")
terraform apply "${ARGS[@]}"

BUCKET=$(terraform output -raw s3_frontend_bucket)
DIST_ID=$(terraform output -raw cloudfront_distribution_id)
CF_URL=$(terraform output -raw cloudfront_url)
INNGEST_URL=$(terraform output -raw inngest_url)

# 3. Build + deploy frontend
cd "$ROOT"
npm install
NEXT_EXPORT=1 npm run build
aws s3 sync ./out "s3://$BUCKET/" --delete

# 4. Clear CloudFront cache
aws cloudfront create-invalidation --distribution-id "$DIST_ID" --paths "/*" > /dev/null

echo
echo "Deployment complete!"
echo "App URL     : $CF_URL"
echo "Inngest URL : $INNGEST_URL"
