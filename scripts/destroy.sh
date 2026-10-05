#!/bin/bash
set -e

if [ $# -eq 0 ]; then
  echo "Usage: $0 <dev|test|prod> [project_name]"; exit 1
fi
ENVIRONMENT=$1
PROJECT_NAME=${2:-handseller}
case "$ENVIRONMENT" in dev|test|prod) ;; *) echo "Invalid environment: $ENVIRONMENT"; exit 1;; esac

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/terraform"

if ! terraform workspace list | grep -qE "^\*?\s*${ENVIRONMENT}$"; then
  echo "Workspace '$ENVIRONMENT' does not exist. Available:"; terraform workspace list; exit 1
fi
terraform workspace select "$ENVIRONMENT"

# Terraform reads the Lambda zip even when destroying; use a placeholder if missing
[ -f "$ROOT/lambda-deployment.zip" ] || touch "$ROOT/lambda-deployment.zip"

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
BUCKET="${PROJECT_NAME}-${ENVIRONMENT}-frontend-${ACCOUNT_ID}"
echo "Emptying $BUCKET ..."
aws s3 rm "s3://$BUCKET" --recursive 2>/dev/null || true

SECRETS="$ROOT/terraform/secrets.${ENVIRONMENT}.tfvars"
ARGS=(-var="project_name=$PROJECT_NAME" -var="environment=$ENVIRONMENT" -auto-approve)
[ "$ENVIRONMENT" = "prod" ] && [ -f prod.tfvars ] && ARGS+=(-var-file=prod.tfvars)
[ -f "$SECRETS" ] && ARGS+=(-var-file="$SECRETS")
terraform destroy "${ARGS[@]}"

echo "Infrastructure for ${ENVIRONMENT} destroyed."
echo "To remove the workspace: terraform workspace select default && terraform workspace delete $ENVIRONMENT"
