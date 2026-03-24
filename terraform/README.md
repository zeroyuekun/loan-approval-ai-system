# Infrastructure -- AWS EKS Deployment

Terraform configuration for deploying the AussieLoanAI system to AWS. Provisions an EKS cluster, RDS PostgreSQL database, and ElastiCache Redis instance inside a private VPC.

## Prerequisites

- AWS CLI configured with appropriate credentials
- Terraform >= 1.5
- kubectl

## Deploy

```bash
cd terraform
terraform init
terraform plan -out=plan.tfplan
terraform apply plan.tfplan
```

You will be prompted for `db_password`. To avoid the prompt, create a `terraform.tfvars` file:

```hcl
db_password = "your-secure-password"
```

## Connect to cluster

```bash
aws eks update-kubeconfig --name aussieloanai-production --region ap-southeast-2
```

## Deploy application

```bash
kubectl apply -k ../k8s/
```

## Remote state (production)

For production use, uncomment the S3 backend block in `main.tf` and create the state bucket:

```bash
aws s3 mb s3://aussieloanai-terraform-state --region ap-southeast-2
aws s3api put-bucket-versioning --bucket aussieloanai-terraform-state --versioning-configuration Status=Enabled
```

## Tear down

```bash
terraform destroy
```

Note: RDS has `deletion_protection = true`. Disable it in the console or set `deletion_protection = false` in `rds.tf` before destroying.

## Estimated costs (ap-southeast-2)

| Resource              | Monthly cost |
|-----------------------|-------------|
| EKS control plane     | ~$73        |
| 2x t3.medium nodes    | ~$76        |
| RDS db.t3.micro       | ~$15        |
| ElastiCache t3.micro  | ~$12        |
| NAT Gateway           | ~$32        |
| **Total (dev)**       | **~$208**   |

Production with larger instances (t3.large nodes, db.t3.medium, Multi-AZ RDS): ~$500+/month.
