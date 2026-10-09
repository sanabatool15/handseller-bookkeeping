# Handseller Bookkeeping

Simple bookkeeping for small business owners and handsellers: record sales and expenses, see your numbers on a dashboard, and ask an AI advisor for plain-language financial advice. No accounting jargon, no accountant required.

**Live demo:** https://d31h6duwmiw3k.cloudfront.net/login/

## Features

- Register and log in; every business (org) only ever sees its own data
- Record sales and expenses
- Dashboard with total sales, total expenses and net
- AI financial advisor that runs as a background job and works from your real figures

## Tech stack

| Layer | Technology |
| --- | --- |
| Frontend | Next.js 16, React, Tailwind CSS, Radix UI |
| Backend | FastAPI (Python 3.12) |
| Database | Supabase (Postgres) |
| Cache / idempotency | Redis |
| Background jobs | Inngest |
| AI | OpenAI-compatible API (Gemini today; Amazon Bedrock planned) |
| Hosting | AWS: Lambda, API Gateway, S3, CloudFront |
| Infrastructure | Terraform, deployed with GitHub Actions |

## Repository layout

```
app/, components/, lib/   Next.js frontend (repo root)
api/                      FastAPI backend (see api/README.md for its architecture)
aws/                      Lambda packaging: handler (Mangum) and build script
terraform/                Infrastructure as code (Lambda, API Gateway, S3, CloudFront)
terraform/bootstrap/      One-time setup: Terraform state bucket + GitHub OIDC role
scripts/                  deploy / destroy scripts (PowerShell and bash)
.github/workflows/        CI/CD: deploy.yml and destroy.yml
```

## Run locally

Frontend:

```bash
npm install
npm run dev          # http://localhost:3000
```

Backend (needs its own `.env`):

```bash
cd api
cp .env.example .env     # fill in Supabase, Redis, Inngest and AI keys
pip install -r requirements.txt
uvicorn core.fastapi_app:app --reload --port 8000
```

Set `NEXT_PUBLIC_API_URL` in `.env.local` if the backend is not on the same origin. Apply `api/sql/schema.sql` to your Supabase project first. More detail, tests and architecture notes are in [`api/README.md`](api/README.md).

## How it is deployed on AWS

```
Browser
   |
CloudFront (one URL)
   |-- /api/*  -->  API Gateway  -->  Lambda (FastAPI via Mangum)
   |-- /*      -->  S3 bucket (static Next.js export)
```

- The frontend is built as a static export (`NEXT_EXPORT=1 npm run build`) and served from S3. The backend does not serve the website.
- The API is same-origin through CloudFront, so there are no CORS issues.
- Supabase, Redis, Inngest and the AI provider are reached over the internet, so the Lambda needs no extra AWS permissions.

### Environments

Each environment is a separate Terraform workspace with its own resources named `handseller-<env>-*`:

| Environment | How it deploys |
| --- | --- |
| `develop` | Automatically on every push to `main` |
| `test` | Manually: Actions > Deploy Handseller > Run workflow |
| `prod` | Manually, with a required reviewer |

State is stored remotely in S3 (with native locking). GitHub Actions signs in to AWS with OIDC, so no AWS keys are stored anywhere.

### One-time setup

1. `cd terraform/bootstrap && terraform init && terraform apply` creates the state bucket and the GitHub deploy role.
2. In the GitHub repo add the secrets `AWS_ROLE_ARN` (the role ARN from the bootstrap output) and `TF_SECRETS` (the contents of your secrets tfvars; see `terraform/secrets.auto.tfvars.example`).
3. Create the GitHub environments `develop`, `test` and `prod`.

### Deploy and destroy

From GitHub: Actions > **Deploy Handseller** or **Destroy Handseller environment**.

From your machine (needs AWS credentials, Terraform, Docker, Node and Python):

```powershell
.\scripts\deploy.ps1  -Environment test
.\scripts\destroy.ps1 -Environment test
```

```bash
./scripts/deploy.sh  test
./scripts/destroy.sh test
```

Each deploy prints the app URL and the Inngest sync URL. After the first deploy of an environment, register that Inngest URL (`<app url>/api/inngest`) in the Inngest dashboard.

## Configuration

Backend settings live in `api/.env` locally and in the `lambda_env` map in the Terraform secrets file when deployed. The main ones: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `JWT_SECRET`, `REDIS_URL`, `INNGEST_EVENT_KEY`, `INNGEST_SIGNING_KEY`, `OPENAI_API_KEY`, `OPENAI_API_BASE_URL`, `OPENAI_MODEL`. Never commit `.env` files or `secrets.*.tfvars`; they are git-ignored.
