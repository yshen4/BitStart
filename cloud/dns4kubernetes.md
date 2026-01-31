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

## Certificate management

## Secrets management
