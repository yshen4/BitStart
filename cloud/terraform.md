# Terraform in 1 Hour: From Beginner to Production-Ready (AWS + GCP)

> **Positioning**: This tutorial focuses on the essence of core concepts, the critical workflow, advanced features you can use in production, and multi-cloud patterns for AWS + GCP. Follow the timeline and you will be ready to build real infrastructure.

---

## Part 1: Core Concepts in 10 Minutes

### 1.1 Terraform’s Architecture

Terraform consists of two main parts:

- **Terraform Core** — the binary you download. It parses configuration, builds the dependency graph, and manages state.
```bash
# We will use opentofu, if there is terraform installed, please uninstall it
brew uninstall terraform
brew cleanup

# Install opentofu
brew update
brew install opentofu
tofu version
# OpenTofu v1.13.1
# on darwin_arm64
```
- **Terraform Providers** — independent plugins that know how to talk to target APIs such as AWS, GCP, Kubernetes, etc.

This separation means the same workflow can drive any number of platforms. A provider defines each unit of infrastructure, such as a compute instance or a VPC, as a **resource**. You can combine resources from different providers into reusable configurations called **modules**.

### 1.2 Declarative vs Imperative

Terraform configuration is **declarative**. You describe the desired end state, not the step-by-step commands to build it. The provider automatically calculates dependencies between resources and creates or destroys them in the correct order.

This is fundamentally different from imperative tools like Ansible. Terraform cares about “what the final result should be.” Ansible cares about “what steps to run.”

### 1.3 The Nature of the State File

The state file is Terraform’s **source of truth**. It is a JSON mapping between resources defined in your configuration and real infrastructure resources in the cloud.

On every `terraform apply`, Terraform compares the state file with real infrastructure and your code, then decides whether to create, update, or destroy resources.

**Key insight**: The state file is not just a record. It is the basis for diff calculation and dependency resolution. If you lose the state file, Terraform “forgets” the infrastructure it manages — even if the resources still exist.

---

## Part 2: The Critical Workflow (0:10–0:20)

### 2.1 The Five-Step Workflow

The standard Terraform workflow is:

**Scope → Author → Initialize → Plan → Apply**

- **Init** — downloads providers and modules, connects to remote state.
- **Plan** — generates an execution plan and previews changes. This is your safety net.
- **Apply** — executes the plan and calls cloud APIs to create, update, or delete resources.

### 2.2 Must-Know CLI Commands

```bash
tofu init                    # Initialize, download providers and modules
tofu plan -out=plan.tfplan   # Generate and save a plan
tofu apply plan.tfplan       # Apply a saved plan, avoiding drift between confirmation and execution
tofu destroy                 # Destroy all managed resources
tofu state list              # List all resources tracked in state
tofu state show <resource>   # Show detailed state for one resource
tofu import <resource> <id>  # Import existing infrastructure into state
tofu fmt                     # Format code
tofu validate                # Validate syntax
```

### 2.3 Remote State Configuration

**Never use local state in production or team environments.** Local state has no locking, no backup, and no version control. Concurrent operations can corrupt it, and accidental deletion can lose everything.

#### AWS S3 Backend

Use S3 with native lock files in Terraform 1.10+ instead of DynamoDB:

```hcl
# backend.tf
terraform {
  backend "s3" {
    bucket       = "my-terraform-state"
    key          = "prod/vpc/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true   # Native S3 locking, Terraform 1.10+
  }
}
```

#### GCP GCS Backend

```hcl
terraform {
  backend "gcs" {
    bucket = "my-terraform-state-gcp"
    prefix = "prod/vpc"
  }
}
```

Cross-cloud backend mapping:

- AWS: S3 + native lock file
- GCP: GCS bucket

Both support versioning and encryption.

---

## Part 3: Advanced Features (0:20–0:40)

### 3.1 Dynamic Blocks — Eliminate Repetition

Dynamic blocks are one of the most practical advanced features in Terraform. When you need to repeat nested blocks inside a resource — such as multiple ingress rules in a security group or multiple listeners in a load balancer — dynamic blocks let you generate those nested blocks programmatically from variables or data structures.

#### Example: Dynamic Ingress Rules for an AWS Security Group

```hcl
variable "ingress_rules" {
  type = list(object({
    from_port   = number
    to_port     = number
    protocol    = string
    cidr_blocks = list(string)
    description = string
  }))

  default = [
    {
      from_port   = 443
      to_port     = 443
      protocol    = "tcp"
      cidr_blocks = ["0.0.0.0/0"]
      description = "HTTPS"
    },
    {
      from_port   = 80
      to_port     = 80
      protocol    = "tcp"
      cidr_blocks = ["0.0.0.0/0"]
      description = "HTTP"
    }
  ]
}

resource "aws_security_group" "web" {
  name   = "web-sg"
  vpc_id = aws_vpc.main.id

  dynamic "ingress" {
    for_each = var.ingress_rules
    content {
      from_port   = ingress.value.from_port
      to_port     = ingress.value.to_port
      protocol    = ingress.value.protocol
      cidr_blocks = ingress.value.cidr_blocks
      description = ingress.value.description
    }
  }
}
```

The same pattern works for GCP firewall rules:

```hcl
resource "google_compute_firewall" "web" {
  name    = "web-firewall"
  network = google_compute_network.main.name

  dynamic "allow" {
    for_each = var.ingress_rules
    content {
      protocol = allow.value.protocol
      ports    = ["${allow.value.from_port}-${allow.value.to_port}"]
    }
  }
}
```

### 3.2 `for_each` vs `count` — Why `for_each` Is Better

`count` uses numeric indexes to identify resource instances. If you delete an item from the middle of a list, all subsequent indexes shift. Terraform then thinks it must destroy and recreate resources.

`for_each` uses **map keys** as stable identifiers. Deleting one key affects only that resource. Other resources do not drift.

```hcl
# ❌ Dangerous: deleting index=1 causes index=2 to become the new index=1
resource "aws_instance" "web" {
  count = 3
  # ...
}

# ✅ Safe: deleting key "web-b" only affects web-b
resource "aws_instance" "web" {
  for_each = {
    "web-a" = { instance_type = "t3.micro", subnet = "subnet-a" }
    "web-b" = { instance_type = "t3.small", subnet = "subnet-b" }
    "web-c" = { instance_type = "t3.micro", subnet = "subnet-c" }
  }

  instance_type = each.value.instance_type
  subnet_id     = each.value.subnet
}
```

**Rule**: Prefer `for_each`. Use `count` only when resource count is fully dynamic and you do not need stable identity.

### 3.3 Lifecycle Rules — Control Resource Changes

The `lifecycle` meta-argument controls how Terraform creates, updates, and destroys resources.

```hcl
resource "aws_db_instance" "production" {
  # ...

  lifecycle {
    prevent_destroy       = true  # Prevent accidental deletion of production DB
    ignore_changes        = [tags] # Ignore external tag changes
    create_before_destroy = true  # Create new instance before destroying old one, for zero downtime
  }
}
```

- `prevent_destroy` is a production safety bolt. Any `terraform destroy` or replacement operation fails immediately.
- `ignore_changes` is useful for attributes managed by external systems, such as manually added tags.
- `create_before_destroy` is key for zero-downtime deployments.

### 3.4 Module Design — From “Works” to “Maintainable”

A well-designed module raises the abstraction level of your architecture. It should describe a new concept, not simply wrap provider resource types.

Key principles:

- **Keep the module tree flat** — prefer composition over deep nesting.
- **Use standard structure** — each module starts with `main.tf` and includes `variables.tf`, `outputs.tf`, and `README.md`.
- **Small scope beats large scope** — smaller modules have a smaller blast radius and better performance.
- **Version semantically** — modules should be versioned and locked with `?ref=v1.2.0`.

```hcl
# Calling child modules from the root module
module "vpc" {
  source = "./modules/vpc"
  cidr   = "10.0.0.0/16"
  azs    = ["us-east-1a", "us-east-1b"]
}

module "web_cluster" {
  source     = "./modules/web"
  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnet_ids
  count      = var.environment == "prod" ? 3 : 1
}
```

### 3.5 Variables and Locals — Keep Code DRY

```hcl
variable "environment" {
  type        = string
  description = "Deployment environment"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be dev, staging, or prod."
  }
}

variable "instance_type" {
  type    = string
  default = "t3.micro"
}

locals {
  common_tags = {
    Environment = var.environment
    ManagedBy   = "terraform"
    Project     = var.project_name
  }

  name_prefix = "${var.project_name}-${var.environment}"
}
```

Variable validation blocks catch bad input at the module boundary. This is a recommended module design practice.

---

## Part 4: AWS + GCP Multi-Cloud Configuration (0:40–0:50)

### 4.1 Provider Configuration and Aliases

Terraform supports multiple providers in the same configuration. For multi-cloud, the key is understanding how provider blocks configure different clouds in one workflow.

```hcl
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }

    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
  alias  = "us_east"
}

provider "aws" {
  region = "eu-west-1"
  alias  = "eu_west"
}

provider "google" {
  project = var.gcp_project_id
  region  = "us-central1"
}
```

### 4.2 Cross-Cloud Resource Dependencies

Terraform’s dependency graph naturally supports cross-cloud dependencies. When you reference an AWS resource attribute to configure a GCP resource, Terraform automatically recognizes the cross-cloud dependency and creates the AWS resource before the GCP resource.

```hcl
# AWS: create an EC2 instance
resource "aws_instance" "web" {
  provider      = aws.us_east
  ami           = "ami-0c55b1b455e52cb05"
  instance_type = "t3.micro"
  tags          = local.common_tags
}

# GCP: create a firewall rule allowing traffic from the AWS instance IP
resource "google_compute_firewall" "allow_aws" {
  name    = "allow-aws-traffic"
  network = google_compute_network.main.name

  allow {
    protocol = "tcp"
    ports    = ["443"]
  }

  source_ranges = ["${aws_instance.web.public_ip}/32"]  # Cross-cloud dependency
}
```

### 4.3 Multi-Cloud State Strategy

**Core principle: each cloud should have its own state file.**

Do not try to put all cloud resources into one state. Reasons:

1. Larger blast radius — a corrupted state in one cloud can affect the other.
2. Different deployment frequencies and change cadences.
3. Cleaner permission isolation.

Recommended structure:

```text
infra/
├── aws/
│   ├── backend.tf          # S3 backend
│   ├── vpc/
│   ├── ec2/
│   └── rds/
└── gcp/
    ├── backend.tf          # GCS backend
    ├── network/
    └── gke/
```

If you need to share data between clouds, such as CIDR planning, use the `terraform_remote_state` data source:

```hcl
data "terraform_remote_state" "aws_network" {
  backend = "s3"

  config = {
    bucket = "my-terraform-state"
    key    = "aws/vpc/terraform.tfstate"
    region = "us-east-1"
  }
}
```

Then reference it from GCP configuration:

```hcl
resource "google_compute_network" "peered" {
  name                    = "peered-network"
  auto_create_subnetworks = false
}
```

**Note**: Use `terraform_remote_state` only at true ownership boundaries. Do not abuse it as a general data-passing mechanism.

### 4.4 Multi-Cloud Provider Authentication

#### AWS Authentication

Use environment variables or IAM roles:

```bash
export AWS_ACCESS_KEY_ID="..."
export AWS_SECRET_ACCESS_KEY="..."

# Or use a profile
export AWS_PROFILE="my-profile"
```

#### GCP Authentication

Use a service account or Workload Identity Federation:

```bash
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"
```

In production, prefer **OIDC / Workload Identity Federation** over static keys:

- AWS uses IAM OIDC.
- GCP uses Workload Identity Federation.

Both allow CI/CD pipelines to obtain temporary credentials safely.

---

## Part 5: Production Best Practices and Cheat Sheet (0:50–1:00)

### 5.1 Production Best Practices

#### State Management

- Always use a remote backend with encryption and versioning.
- Split state by environment and component. Do not manage everything in one state.
- In CI/CD, generate a plan file first: `terraform plan -out=plan.tfplan`, then run `terraform apply plan.tfplan`. This avoids drift between confirmation and execution.

#### Code Organization

- Use `for_each` instead of `count` for resource collections with stable identities.
- Keep modules flat. Prefer composition over nesting.
- Always write `type` and `description` for variables. Add `validation` for critical variables.
- Apply standard tags to all resources: `Environment`, `ManagedBy`, `Project`.

#### Security

- Mark sensitive variables with `sensitive = true`.
- State files contain sensitive data. Restrict access to S3/GCS buckets strictly.
- Use `prevent_destroy` to protect production databases and critical resources.

#### Testing and CI/CD

- Run `terraform fmt` and `terraform validate` before commits.
- Use `tflint` for linting and `tfsec` or `checkov` for security scanning.
- Automatically generate `terraform plan` in pull requests and post it as a comment.
- Use Terratest or `terraform test` for integration testing.

### 5.2 Common Pitfalls Cheat Sheet

| Pitfall | Symptom | Fix |
|---|---|---|
| Local state | State conflicts during team collaboration | Migrate to a remote backend |
| `count` index drift | Deleting a middle resource causes others to be recreated | Use `for_each` |
| Missing `prevent_destroy` | `terraform destroy` accidentally deletes production DB | Add lifecycle protection to critical resources |
| Hardcoded values | Lots of duplicated code across environments | Use variables + locals + modules |
| Provider version not locked | Unexpected breaking changes after upgrade | Lock versions in `required_providers` |
| One state for everything | `plan` takes minutes; large blast radius | Split state by environment/component |

### 5.3 1-Hour Time Allocation

| Time | Topic | Action |
|---|---|---|
| 0:00–0:10 | Core concepts | Understand state, declarative vs imperative |
| 0:10–0:20 | Critical workflow | Configure remote state; master plan/apply/import |
| 0:20–0:40 | Advanced features | Practice dynamic blocks, `for_each`, lifecycle, modules |
| 0:40–0:50 | AWS + GCP multi-cloud | Configure dual providers; understand cross-cloud dependencies and state strategy |
| 0:50–1:00 | Best practices and cheat sheet | Review pitfalls against your own code |

---

## Practical Starting Point: A Minimal Runnable Example

The following configuration creates basic network resources in both AWS and GCP. Use it as a starting point for multi-cloud infrastructure.

```hcl
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }

    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

provider "google" {
  project = var.gcp_project_id
  region  = "us-central1"
}

# ---------- AWS ----------
resource "aws_vpc" "main" {
  cidr_block = "10.0.0.0/16"
  tags       = local.common_tags
}

resource "aws_subnet" "private" {
  vpc_id     = aws_vpc.main.id
  cidr_block = "10.0.1.0/24"

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-private"
  })
}

# ---------- GCP ----------
resource "google_compute_network" "main" {
  name                    = "${local.name_prefix}-network"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "private" {
  name          = "${local.name_prefix}-subnet"
  ip_cidr_range = "10.1.0.0/24"
  region        = "us-central1"
  network       = google_compute_network.main.id
}

# ---------- Shared Variables ----------
variable "gcp_project_id" {
  type        = string
  description = "GCP project ID"
}

variable "environment" {
  type    = string
  default = "dev"
}

locals {
  name_prefix = "myapp-${var.environment}"

  common_tags = {
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

output "aws_vpc_id" {
  value = aws_vpc.main.id
}

output "gcp_network" {
  value = google_compute_network.main.name
}
```

You now have a complete framework from core concepts to multi-cloud practice. The next step is to **build**. Start with the example above, then add the resources you actually need — EC2/GCE instances, RDS/Cloud SQL, security groups/firewall rules — and deepen your understanding through practice.

Remember the essence of Terraform: **declare what you want, and let the tool calculate how to get there.**
