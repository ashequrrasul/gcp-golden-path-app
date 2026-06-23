# ecommerce-product-service

Application repository for the GCP Golden Path.

This repo owns:

- FastAPI backend service
- Unit tests
- Docker image build
- Container image scan
- Push to Google Artifact Registry
- Updating the deployment repo with the new Helm image tag

Terraform, Helm, ArgoCD, monitoring, and environment configuration live in the deployment repo:

Repository: `ashequrrasul/gcp-golden-path-platform`

## Required GitHub Settings

Repository variable:

```text
GCP_PROJECT_ID
```

Repository secrets:

```text
GCP_WORKLOAD_IDENTITY_PROVIDER
GCP_DEPLOYER_SERVICE_ACCOUNT
DEPLOY_REPO_TOKEN
```

`DEPLOY_REPO_TOKEN` must have permission to push to the deployment repo, or preferably open a PR into it.

## Deploy Flow

```text
push to main
-> tests
-> Docker build
-> Trivy image scan
-> push image to Artifact Registry
-> update image tag in gcp-golden-path-platform
-> ArgoCD syncs deployment repo to GKE
```
