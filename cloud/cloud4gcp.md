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

## cloud-network-service - VPC and networking
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

## cloud-k8s-service - GKE cluster and node pools

## cloud-storage-service - GCS buckets for Pinot deep storage
