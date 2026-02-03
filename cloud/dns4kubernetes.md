# DNS and routing for Kubernetes cluster

The workflow can be illustrated as follows:
```yaml
                    External Traffic
                          │
                          ▼
              ┌──────────────────────┐
              │  Cloud Load Balancer │ (AWS ELB/Azure LB/GCP LB)
              └──────────────────────┘
                          │
                          ▼
              ┌──────────────────────┐
              │  Traefik Ingress     │ (ingress-external)
              │  (LoadBalancer svc)  │
              └──────────────────────┘
                          │
                          ▼
              ┌──────────────────────┐
              │  IngressRoute CRDs   │ (Host/Path routing + TLS)
              └──────────────────────┘
                          │
                          ▼
              ┌──────────────────────┐
              │  Backend Services    │
              └──────────────────────┘
```

## DNS Registration Workflow
Architecture:
- Cloud-DNS Service (cloud-dns/) manages DNS records
- AWS Route53 is the centralized DNS provider for ALL clouds (AWS, Azure, GCP)

Here is the workflow:
```yaml
Route53Manager
 ├── CreateHostedZone()
 │    └── create public hosted zone
 │    └── return HostedZoneID + NameServers
 │
 ├── SetupNSInParentZone()
 │    └── create NS record in parent hosted zone
 │
 ├── BuildRecordSets()
 │    └── extract IPs from network status
 │    └── supports AWS ELB EIPs / internal ELB IPs
 │
 └── ApplyRecordSets()
      └── ChangeResourceRecordSets
```

Here is an example Route53Manager in golang:
```go
package dns

import (
	"context"
	"fmt"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/route53"
	"github.com/aws/aws-sdk-go-v2/service/route53/types"
)

type NetworkConfig struct {
	ElbEips        []string // public ELB EIPs
	InternalElbIps []string // private NLB/ELB IPs
}

type Route53Manager struct {
	client *route53.Client
}

func NewRoute53Manager(cfg aws.Config) *Route53Manager {
	return &Route53Manager{
		client: route53.NewFromConfig(cfg),
	}
}

// Create DNS Zone (Hosted Zone)
func (m *Route53Manager) CreateHostedZone(
	ctx context.Context,
	domain string,
) (zoneID string, nameServers []string, err error) {
	resp, err := m.client.CreateHostedZone(ctx, &route53.CreateHostedZoneInput{
		Name: aws.String(domain),
		CallerReference: aws.String(
			fmt.Sprintf("%s-%d", domain, time.Now().Unix()),
		),
		HostedZoneConfig: &types.HostedZoneConfig{
			Comment:     aws.String("Managed by Go"),
			PrivateZone: aws.Bool(false),
		},
	})
	if err != nil {
		return "", nil, err
	}

	for _, ns := range resp.DelegationSet.NameServers {
		nameServers = append(nameServers, ns)
	}

	return aws.ToString(resp.HostedZone.Id), nameServers, nil
}

// Setup NS records in parent zone
func (m *Route53Manager) SetupNSInParentZone(
	ctx context.Context,
	parentZoneID string,
	subDomain string,
	nameServers []string,
) error {
	var records []types.ResourceRecord
	for _, ns := range nameServers {
		records = append(records, types.ResourceRecord{
			Value: aws.String(ns),
		})
	}
	_, err := m.client.ChangeResourceRecordSets(ctx,
		&route53.ChangeResourceRecordSetsInput{
			HostedZoneId: aws.String(parentZoneID),
			ChangeBatch: &types.ChangeBatch{
				Changes: []types.Change{
					{
						Action: types.ChangeActionUpsert,
						ResourceRecordSet: &types.ResourceRecordSet{
							Name: aws.String(subDomain),
							Type: types.RRTypeNs,
							TTL:  aws.Int64(300),
							ResourceRecords: records,
						},
					},
				},
			},
		},
	)
	return err
}

//Generate DNS RecordSet entity
func BuildARecordSet(
	domain string,
	ips []string,
) *types.ResourceRecordSet {
	var records []types.ResourceRecord
	for _, ip := range ips {
		records = append(records, types.ResourceRecord{
			Value: aws.String(ip),
		})
	}
	return &types.ResourceRecordSet{
		Name: aws.String(domain),
		Type: types.RRTypeA,
		TTL:  aws.Int64(60),
		ResourceRecords: records,
	}
}

//Extract IPs from network status
func ExtractIPs(cfg NetworkConfig) []string {
	var ips []string

	if len(cfg.ElbEips) > 0 {
		ips = append(ips, status.ElbEips...)
	}

	if len(cfg.InternalElbIps) > 0 {
		ips = append(ips, status.InternalElbIps...)
	}

	return ips
}

//Set DNS RecordSets (ChangeResourceRecordSets)
func (m *Route53Manager) ApplyRecordSets(
	ctx context.Context,
	zoneID string,
	recordSets []*types.ResourceRecordSet,
) error {
	var changes []types.Change
	for _, rs := range recordSets {
		changes = append(changes, types.Change{
			Action:            types.ChangeActionUpsert,
			ResourceRecordSet: rs,
		})
	}

	_, err := m.client.ChangeResourceRecordSets(ctx,
		&route53.ChangeResourceRecordSetsInput{
			HostedZoneId: aws.String(zoneID),
			ChangeBatch: &types.ChangeBatch{
				Changes: changes,
			},
		},
	)

	return err
}
```

Here is an example with complete workflow:
```go
/*
   url: "app.example.com"
 	 cfg := NetworkConfig{
		ElbEips: []string{
			"34.210.12.3",
			"54.188.92.10",
		},
	}
*/
func ExampleUsage(cfg aws.Config, url String, cfg NetworkConfig) error {
	ctx := context.Background()
	r53 := NewRoute53Manager(cfg)

	zoneID, ns, err := r53.CreateHostedZone(ctx, url)
	if err != nil {
		return err
	}

	err = r53.SetupNSInParentZone(
		ctx,
		"Z_PARENT_ZONE_ID",
		url,
		ns,
	)
	if err != nil {
		return err
	}

	ips := ExtractIPs(cfg)
	aRecord := BuildARecordSet(url, ips)
	return r53.ApplyRecordSets(ctx, zoneID, []*types.ResourceRecordSet{
		aRecord,
	})
}
```

## Load balancer
Kubernetes core provides Service types, not a full L7 load balancer:

Kuberntes has 4 types of Service, 3 (ClusterIP / NodePort / LoadBalancer) are related to load balancing:
   A. ClusterIP: Internal-only, L4 (TCP/UDP), no routing, no TLS, no HTTP awareness
   B. NodePort: Exposes a port on every node, crude, not production-friendly
   C. LoadBalancer: Asks the cloud provider (AWS/GCP/Azure) to create an external L4 LB, still no HTTP routing, no path-based rules, no middleware

These are transport-level (L4) tools. Kuberntes does not ship an L7 HTTP reverse proxy.

### Traefik
Traefik is an Ingress Controller, which sits on top of Kubernetes primitives.
1. Layer 7 (HTTP) routing
```yaml
/api  → service A
/web  → service B
/     → service C
```
2. Ingress = declarative routing: Traefik watches the API server, dynamically reconfigures itself, no reloads, no restarts
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
```
3. TLS done properly: Traefik handles TLS termination, SNI, Automatic certs (Let’s Encrypt), HTTP → HTTPS redirects
4. Middleware & traffic shaping: Traefik does Auth (basic, OIDC), Rate limiting, Retries / timeouts, Headers, redirects, rewrites, Canary / weighted routing
5. Dynamic, cloud-agnostic: Same config on AWS / GCP / on-prem

```yaml
Internet
   ↓
Cloud L4 LoadBalancer (Service type=LoadBalancer)
   ↓
Traefik Pods
   ↓
ClusterIP Services
   ↓
Pods
```

## Certificate management
We study the workflow using cert-manager for certificate management with DNS-01 challenges via AWS Route53. The workflow creates dedicated IAM users with scoped permissions for each DNS zone to allow cert-manager to create DNS TXT records for ACME validation.

There are 2 types of certificates:
1. Internal certificates (CA-based): internal service-to-service TLS
2. External Certificates (ACME with DNS-01): validated via DNS-01 challenges against Route53

Here is DNS-01 challenge flow:
```yaml
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Certificate Request Flow                             │
└─────────────────────────────────────────────────────────────────────────────┘

1. Certificate Resource Created
   │
   ▼
┌─────────────────┐
│  cert-manager   │ ──── Requests certificate from ACME server
└─────────────────┘
   │
   ▼
2. ACME Server Returns DNS Challenge
   │  (Create TXT record: _acme-challenge.domain.com)
   ▼
┌─────────────────┐      ┌─────────────────┐
│  cert-manager   │ ───▶ │  AWS Route53    │  Creates TXT record
└─────────────────┘      └─────────────────┘
   │                      using IAM credentials
   │                      from Kubernetes Secret
   ▼
3. ACME Server Validates DNS Record
   │
   ▼
4. Certificate Issued → Stored in Kubernetes Secret
```

Here is the workflow from create DNS zone to certificate use:
```
1. DNS Zone Creation (controlplane/pkg/service/dns/zone.go)
   ├── Create Route53 hosted zone
   ├── Create NS records in parent zone
   ├── Create IAM user: cert-manager-<zone-name>
   ├── Attach IAM policy with Route53 permissions
   ├── Generate access keys
   └── Store credentials as Kubernetes Secret (route53)

2. Issuer Deployment (Helm)
   ├── Deploy Issuer with Route53 DNS-01 solver
   └── Reference the route53 secret for credentials

3. Certificate Creation (Helm)
   ├── Create Certificate resource with dnsNames
   └── Reference the Issuer

4. cert-manager Processing
   ├── Detect new Certificate resource
   ├── Request ACME challenge from Let's Encrypt/GCP
   ├── Create TXT record in Route53 (_acme-challenge.domain)
   ├── Wait for ACME validation
   ├── Receive signed certificate
   └── Store in Kubernetes Secret (external-tls)

5. Traefik Uses Certificate
   └── IngressRoute references secretName for TLS termination
```

## Secrets management


