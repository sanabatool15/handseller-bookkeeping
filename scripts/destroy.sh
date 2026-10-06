#!/bin/bash
set -e

if [ $# -eq 0 ]; then
  echo "Usage: $0 <develop|test|prod|dev> [project_name]  (dev = original stack in the default workspace)"; exit 1
fi
ENVIRONMENT=$1
PROJECT_NAME=${2:-handseller}
case "$ENVIRONMENT" in dev|develop|test|prod) ;; *) echo "Invalid environment: $ENVIRONMENT"; exit 1;; esac

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/terraform"

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=${DEFAULT_AWS_REGION:-eu-north-1}
terraform init -input=false -reconfigure \
  -backend-config="bucket=${PROJECT_NAME}-terraform-state-${ACCOUNT_ID}" \
  -backend-config="key=terraform.tfstate" \
  -backend-config="region=${AWS_REGION}" \
  -backend-config="use_lockfile=true" \
  -backend-config="encrypt=true"

# The original manual-era stack ("dev") lives in the default workspace
WORKSPACE=$ENVIRONMENT
[ "$ENVIRONMENT" = "dev" ] && WORKSPACE=default
if ! terraform workspace list | grep -qE "^\*?\s*${WORKSPACE}$"; then
  echo "Workspace '$WORKSPACE' does not exist. Available:"; terraform workspace list; exit 1
fi
terraform workspace select "$WORKSPACE"

# Terraform reads the Lambda zip even when destroying; use a placeholder if missing
[ -f "$ROOT/lambda-deployment.zip" ] || touch "$ROOT/lambda-deployment.zip"

BUCKET="${PROJECT_NAME}-${ENVIRONMENT}-frontend-${ACCOUNT_ID}"
echo "Emptying $BUCKET ..."
aws s3 rm "s3://$BUCKET" --recursive 2>/dev/null || true

SECRETS="$ROOT/terraform/secrets.${ENVIRONMENT}.tfvars"
ARGS=(-var="project_name=$PROJECT_NAME" -var="environment=$ENVIRONMENT" -auto-approve)
[ "$ENVIRONMENT" = "prod" ] && [ -f prod.tfvars ] && ARGS+=(-var-file=prod.tfvars)
[ -f "$SECRETS" ] && ARGS+=(-var-file="$SECRETS")
terraform destroy "${ARGS[@]}"

echo "Infrastructure for ${ENVIRONMENT} destroyed."
[ "$WORKSPACE" != "default" ] && echo "To remove the workspace: terraform workspace select default && terraform workspace delete $WORKSPACE"
