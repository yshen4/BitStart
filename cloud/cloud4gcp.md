# Provision Kubernetes on GCP

The overall workflow follows: 
```
1. Network Service creates:
   └── VPC → Node Subnet (with pod/service secondary ranges) → Firewall Rules → Cloud NAT → Internal LB Subnet

2. K8s Service creates:
   └── Service Accounts → GKE Cluster → Node Pools (with autoscaling, private nodes)
   └── Post-create: Install StorageClasses via Kubernetes API

3. Storage Service creates:
   └── GCS Bucket → IAM bindings with Workload Identity
```

## GCP basics
- [Google Cloud Full Course for Beginners](https://youtu.be/lvZk_sc8u5I?si=-cyL7wXqa2-b2pA6)
- [Cloud Computing and GCP Fundamentals](https://www.coursera.org/learn/gcp-professional-architect-cloud-computing-and-gcp-fundamentals)

## GCP network service: VPC and networking
Network Provisioning uses Terraform: cloud-network-service/terraform/gcp/v2.2.0/01-terraform-network.tf

### VPC and subnets
```terraform
# Regional VPC with manual subnet creation
resource "google_compute_network" "vpc" {
  name                    = var.vpc_name
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"
}

output "vpc_id" {
  description = "ID of the VPC"
  value       = google_compute_network.vpc.id
}

# Define a subnet within the VPC
resource "google_compute_subnetwork" "network_subnet" {
  name          = var.subnet_name
  ip_cidr_range = var.cidr_range #"10.0.0.0/24"
  region        = var.region #"us-central1"
  network       = google_compute_network.vpc.id

  # Secondary ranges for pods
  secondary_ip_range {
    range_name    = "pods"
    ip_cidr_range = var.pod_cidr_range
  }

  # Secondary ranges for services
  secondary_ip_range {
    range_name    = "services"
    ip_cidr_range = var.service_cidr_range
  }

  # Enable VPC Flow Logs for network traffic visibility
  log_config {
    aggregation_interval = "INTERVAL_30_SEC"
    flow_sampling        = 0.5
    metadata            = "INCLUDE_ALL_METADATA"
  }
}

# Output the name and link of the created subnet
output "network_subnet_name" {
  description = "Name of the subnet"
  value       = google_compute_subnetwork.network_subnet.name
}

output "subnet_self_link" {
  value = google_compute_subnetwork.network_subnet.self_link
}
```

### Firewall rules
```terraform
# Create a firewall rule to allow public HTTP/HTTPS access
resource "google_compute_firewall" "allow_public_http" {
  name    = "${var.vpc_name}-allow-public-http"
  network = google_compute_network.vpc.name
  direction = "INGRESS"
  priority = 1000 # Lower priority numbers have higher precedence

  # The source IP range 0.0.0.0/0 means any IPv4 address (public internet)
  source_ranges = ["0.0.0.0/0"] 

  # The rule applies to instances that have this tag
  # target_tags = ["http-server"] 

  allow {
    protocol = "tcp"
    ports    = ["80", "443"]
  }

  # Optional: Enable logging for this firewall rule
  log_config {
    enable = true
    metadata = "INCLUDE_ALL_METADATA"
  }

  description = "Allow incoming HTTP/HTTPS traffic"
}

# Create a firewall rule to allow public IP access
resource "google_compute_firewall" "allow_public_ips" {
  name    = "${var.vpc_name}-allow-public-ips"
  network = google_compute_network.vpc.name
  
  # Set direction to INGRESS for incoming traffic
  direction = "INGRESS"

  # Specify the external source IP ranges in CIDR format: ["203.0.113.1/32", "198.51.100.0/24"]
  source_ranges = var.ip_ranges_allowed 

  # Apply the rule only to instances with the 'web-servers' tag
  # target_tags = ["web-servers"]

  # Define the protocols and ports to allow
  allow {
    protocol = "tcp"
    ports    = ["80", "443", "22"]
  }

  allow {
    protocol = "udp"
    ports    = ["53"]
  }

  description = "Allow incoming web traffic from specific external IPs"
}
```
### Routing
Cloud NAT (Egress)
```terraform
resource "google_compute_router" "router" {
  name    = "${var.vpc_name}-router"
  region  = var.region
  network = google_compute_network.vpc.id
}

resource "google_compute_address" "nat_ips" {
  name         = "${var.vpc_name}-nat-ip"
  region       = var.region
  address_type = "EXTERNAL"
}

resource "google_compute_router_nat" "nat" {
  name                               = "${var.vpc_name}-nat"
  router                            = google_compute_router.router.name
  nat_ip_allocate_option            = "MANUAL_ONLY"
  nat_ips                           = [google_compute_address.nat_ips.self_link]
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}
```

### Load balancer

```terraform
# Static IP for public load balancer (the same as AWS EIP)
resource "google_compute_address" "static_ips" {
  name         = "${var.vpc_name}-static-ip"
  region       = var.region
  address_type = "EXTERNAL"
}

# Subnet for internal load balancer
resource "google_compute_subnetwork" "internal_lb_subnet" {
  name          = "${var.vpc_name}-internal-lb"
  ip_cidr_range = var.internal_lb_cidr
  region        = var.region
  network       = google_compute_network.vpc.id

  private_ip_google_access = var.private_google_access

  # Enable VPC Flow Logs for network traffic visibility
  log_config {
    aggregation_interval = "INTERVAL_5_SEC"
    flow_sampling        = 0.5
    metadata            = "INCLUDE_ALL_METADATA"
  }
}

# Internal IP address for internal load balancer from the internal-lb subnet
# GCP reserves the first two IPs (index 0: network, index 1: gateway)
# Use index 2 for the first usable IP (typically 10.0.0.2 for a /29 subnet)
resource "google_compute_address" "internal_lb_static_ip" {
  name         = "${var.vpc_name}-internal-lb-ip"
  region       = var.region
  subnetwork   = google_compute_subnetwork.internal_lb_subnet.id
  address_type = "INTERNAL"
  address      = cidrhost(var.internal_lb_cidr, 2) # 3rd IP (0=network, 1=gateway, 2=first usable)
  purpose      = "GCE_ENDPOINT"
}

output "static_ips" {
  description = "Static IP addresses for load balancer"
  value = [
    for static_ip in google_compute_address.static_ips :
    {
      id         = static_ip.id
      ip_address = static_ip.address
    }
  ]
}
```

## GCP k8s service: GKE cluster and node pools

Service accounts in GCP and K8s are specialized, non-human identities used by applications and workloads to securely authenticate and access resources.

| Feature          | GCP Service Account (GSA)                         | Kubernetes Service Account (KSA)          | AWS IAM Role                               | AWS Principal                                      |
|------------------|--------------------------------------------------|-------------------------------------------|---------------------------------------------|---------------------------------------------------|
| Scope            | Google Cloud Project (Infrastructure)            | Kubernetes Cluster / Namespace             | AWS Account / Resource                      | AWS Account / Resource                            |
| Authentication  | OAuth2 / JSON Keys                               | Bearer Tokens                              | STS (AssumeRole, Temporary Credentials)     | SigV4 / STS / Federation                          |
| Primary Use     | Accessing GCP API services (Storage, DBs)        | Accessing Kubernetes API server            | Granting permissions to workloads/services  | Identifying an entity making AWS API requests     |

### Service account
We create 2 dedicated service accounts, one for the cluster, the other for node pool:
```terraform
resource "google_service_account" "cluster" {
  account_id   = "${var.service_account}-cluster"
  display_name = "GKE Cluster Service Account"
}

resource "google_service_account" "node_pool" {
  account_id   = "${var.service_account}-node-pool"
  display_name = "GKE Node Pool Service Account"
}
```

### Cluster
Define the variables
```terraform
variable "project_id" {
  description = "The GCP project ID"
  type        = string
}

variable "region" {
  description = "The GCP region for the cluster"
  type        = string
  default     = "us-central1"
}

variable "cluster_name" {
  description = "The name of the GKE cluster"
  type        = string
  default     = "my-gke-cluster"
}

variable "node_count" {
  description = "The number of nodes in the node pool"
  type        = number
  default     = 1
}

variable "machine_type" {
  description = "The machine type for the GKE nodes"
  type        = string
  default     = "e2-medium"
}
```

```terraform
#
#
# 
module "gke" {
  source  = "terraform-google-modules/kubernetes-engine/google"
  version = "~> 35.0"

  # Basic cluster configuration
  project_id             = var.project_id
  name                   = var.cluster_name
  regional               = var.cluster_type == "regional"
  region                 = var.region
  zones                  = var.zones
  network                = var.network
  subnetwork             = var.subnetwork
  
  # Kubernetes version
  kubernetes_version     = var.kubernetes_version
  
  # Network configuration
  ip_range_pods          = var.ip_range_pods
  ip_range_services      = var.ip_range_services
  default_max_pods_per_node = var.default_max_pods_per_node
  
  # Add-ons
  horizontal_pod_autoscaling = true
  http_load_balancing        = true
  
  # Release channel - UNSPECIFIED to prevent auto-updates
  release_channel = "UNSPECIFIED"
  
  # L4 ILB subsetting for private networks
  enable_l4_ilb_subsetting = var.enable_l4_ilb_subsetting

  # Node pools - default removed, custom pools created
  remove_default_node_pool = true
  node_pools = [
    {
      name           = "${var.cluster_name}-preemptible-pool"
      machine_type   = "e2-medium"
      preemptible    = true
      service_account = google_service_account.node_pool.email
      oauth_scopes = [
        "https://www.googleapis.com/auth/cloud-platform"
      ]
      min_count = 0
      max_count = 5
      image_type         = "COS_CONTAINERD"
      disk_size_gb       = 50
      autoscaling        = true
      auto_upgrade       = true
    }
  ]
}
```


## GCP storage service: GCS buckets for Pinot deep storage

### Provision google bucket
```terraform
variable "gcs_bucket_soft_delete_retention_seconds" {
  description = "Soft delete retention period for GCS bucket (seconds)"
  type        = number
  default     = 2592000 # 30 days
}

resource "google_storage_bucket" "data_bucket" {
  name     = "${var.project_id}-data-bucket"
  project  = var.project_id
  location = "US"
  storage_class = "STANDARD"
  uniform_bucket_level_access = true

  # Soft delete for recovery
  soft_delete_policy {
    retention_duration_seconds = var.gcs_bucket_soft_delete_retention_seconds
  }

  versioning {
    enabled = true
  }

  # Delete all versions after 90 days
  lifecycle_rule {
    condition {
      age = 90
    }
    action {
      type = "Delete"
    }
  }
}
```
### Install storage class
| Storage Class                | Disk Type             | Reclaim Policy | Default           |
|------------------------------|---------------------|----------------|-----------------|
| pd-ssd-default               | pd-ssd              | Delete         | Yes             |
| pd-ssd-retain                | pd-ssd              | Retain         | No              |
| hyperdisk-balanced-default   | hyperdisk-balanced  | Delete         | No (n4 nodes only) |
| hyperdisk-balanced-retain    | hyperdisk-balanced  | Retain         | No (n4 nodes only) |

Configure the Kubernetes provider to use the GKE cluster credentials.
```terraform
provider "kubernetes" {
  host                   = google_container_cluster.primary.endpoint
  token                  = data.google_client_config.current.access_token
  cluster_ca_certificate = base64decode(google_container_cluster.primary.master_auth.0.cluster_ca_certificate)
}

# Define the custom StorageClass resource.
resource "kubernetes_storage_class" "ssd_storage_class" {
  metadata {
    name = "ssd-retain-sc"
    # Optional: Set this to true to make it the default StorageClass for the cluster, 
    # but ensure no other StorageClass is marked as default first.
    # annotations = {
    #   "storageclass.kubernetes.io/is-default-class" = "true"
    # }
  }
  
  # The provisioner for the GCE Persistent Disk CSI driver
  storage_provisioner = "pd.csi.storage.gke.io"
  
  # Reclaim policy can be "Delete" (default) or "Retain"
  reclaim_policy      = "Retain"

  # Parameters specific to the provisioner. 
  # type: specifies the GCE disk type (pd-standard, pd-balanced, pd-ssd, pd-extreme)
  # fstype: specifies the filesystem type (ext4, xfs)
  parameters = {
    type   = "pd-ssd"
    fstype = "ext4"
  }

  # Optional: Allows resizing of volumes
  allow_volume_expansion = true

  # Optional: Mount options for the PVs provisioned with this StorageClass
  mount_options = ["debug"]
}
```
After applying this Terraform configuration, you can reference the new StorageClass in your PersistentVolumeClaims (PVCs) or StatefulSets by setting the storageClassName field to "ssd-retain-sc". 
```terraform
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: my-ssd-pvc
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
  storageClassName: ssd-retain-sc # Reference the name defined in Terraform
```

## Workload Identity Binding
We configure Workload Identity to grant a KSA to impersonate a GSA. 

| Item | Explanation |
|---|---|
| **Kubernetes Service Account (KSA)** | The account your pods use in the cluster |
| **GCP Service Account (GSA)** | The Google account that has IAM permissions to access GCP resources |
| **Workload Identity Federation (WIF)** | The bridge that allows a KSA to impersonate a GSA |

```yaml
                +----------------------+
                |  Kubernetes Pod      |
                |  (running container) |
                +----------+-----------+
                           |
                           | Uses Service Account
                           v
                +----------------------+
                | Kubernetes SA (KSA)  |
                +----------+-----------+
                           |
                           | Annotated with IAM principal
                           v
                +----------------------+
                | Workload Identity    |
                | Pool (WIF)          |
                +----------+-----------+
                           |
                           | Federated authentication
                           v
                +----------------------+
                | GCP IAM Principal    |
                | (roles/container.*)  |
                +----------+-----------+
                           |
                           | Permissions enforced
                           v
                +----------------------+
                | GCP Resources        |
                | (e.g., GCS Bucket,   |
                |  GKE cluster, etc.)  |
                +----------------------+
```

Step 1: Create service account (see above)
Step 2: Create the google bucket (see above)
Step 3: Grant the access
```terraform
resource "google_storage_bucket_iam_member" "gsa_bucket_access" {
  bucket = google_storage_bucket.data_bucket.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.cluster.email}"
}

```
Step 4: Map KSA to GSA
```terraform
resource "google_service_account_iam_member" "ksa_to_gsa" {
  service_account = google_service_account.data_bucket.name
  role            = "roles/iam.workloadIdentityUser"
  member          = "serviceAccount:${var.project_id}.svc.id.goog[<namespace>/<ksa_name>]"
}
```

Step 5: Annotate KSA in Kubernetes
```
kubectl annotate serviceaccount <ksa_name> \
  iam.gke.io/gcp-service-account=<GSA_EMAIL> \
  -n <namespace>
```

Step 6: Configure pod to use service account
```
apiVersion: v1
kind: Pod
metadata:
  name: my-app
  namespace: <namespace>
spec:
  serviceAccountName: <ksa_name>
  containers:
  - name: app
    image: gcr.io/my-project/my-image
```
