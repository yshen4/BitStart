# Kubernetes for Cloud
In this document, we discuss the architecture how to provision cloud (AWS/GCP/Azure) resources for Kubernetes cluster. The main goal is to under how to support BYOC cluster with control plance.

## Architecture Overview
We use a control plane + deployer services architecture with Terraform as the infrastructure-as-code engine to provision AWS resources. The control plane manages entity lifecycle and orchestrates provisioning, and each cloud service (e.g., cloud-network-service, cloud-k8s-service) receives tasks and executes terraform. 

```yaml
┌─────────────────────────────────────────────────────────────────────────────┐
│                           CONTROL PLANE                                      │
│  ┌──────────────┐    ┌────────────────┐    ┌─────────────────┐              │
│  │ API Services │───▶│  Task Manager  │───▶│   Controller    │              │
│  │ (GRPC/REST)  │    │                │    │ (Task Queue)    │              │
│  └──────────────┘    └────────────────┘    └─────────────────┘              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                             Task Distribution
                                    │
┌───────────────────────────────────▼─────────────────────────────────────────┐
│                         DEPLOYER SERVICES                                    │
│  ┌────────────────────┐  ┌─────────────────────┐  ┌──────────────────────┐  │
│  │ cloud-network-svc  │  │  cloud-k8s-service  │  │  cloud-storage-svc   │  │
│  │   (VPC/Subnets)    │  │   (EKS Cluster)     │  │     (S3/EBS)         │  │
│  └─────────┬──────────┘  └──────────┬──────────┘  └──────────┬───────────┘  │
│            │                        │                        │               │
│            ▼                        ▼                        ▼               │
│       Terraform                Terraform                Terraform            │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                              AWS Resources
```

The general workflow is as follows:
1. User creates entities via API (Account → Network → Kubernetes)
2. Control Plane stores desired state and queues provisioning tasks
3. Task Client polls and dispatches tasks to appropriate deployer services
4. Deployer Services execute Terraform with provider-specific configurations
5. Terraform provisions AWS resources (VPC, EKS, IAM, etc.)
6. Post-provisioning hooks install Kubernetes add-ons (LB controller, Karpenter, storage classes)
7. Status is reported back and stored in the control plane

### Key Components
We maintain parent-child relationships between entities:
```
Account (AWS credentials)
    └── Network (VPC)
            └── Kubernetes (EKS)
                    └── Storage (S3 buckets)
```

The Go code translates entity specs to Terraform variables:
```go
func (p *tfProvider) VarArgs(kube *entity.Kubernetes) ([]string, error) {
	varArgs := []string{
		common.JoinWithEquals(varClusterName, kube.Metadata.Name),
		common.JoinWithEquals(varClusterVersion, kube.Spec.AwsKubernetesSpec.KubernetesVersion),
		common.JoinWithEquals(varVpcId, kube.Spec.AwsKubernetesSpec.VpcId),
		common.JoinWithEquals(varPrivateSubnetIds, privateSubnetsStr),
		common.JoinWithEquals(varPublicSubnetIds, publicSubnetsStr),
		common.JoinWithEquals(varDefaultNodeGroupJson, string(defaultNodeGroupJson)),
		common.JoinWithEquals(varNodeGroupJson, string(nodeGroupsJson)),
		common.JoinWithEquals(varRegion, kube.Spec.Region),
		common.JoinWithEquals(varKarpenterEnabled, strconv.FormatBool(karpenterEnabled)),
		// ...
	}
	return varArgs, nil
}
```

#### 1. Control Plane Services (controlplane/)
The control plane manages entity lifecycle and orchestrates provisioning, which is made of 3 services: API service, Task Manager, and Controller.
```go
type Controller struct {
	ctx             context.Context
	loopTime        time.Duration
	store           *Store
	accountSvc      *entitySvc.Account
	kubernetesSvc   *entitySvc.Kubernetes
	networkSvc      *entitySvc.Network
	storageSvc      *entitySvc.Storage
	// ... more services
}
```

The controller runs a reconciliation loop that:
1. Detects entities needing provisioning (desired state ≠ actual state)
2. Creates tasks with full entity context (account, network, kubernetes, storage)
3. Enqueues tasks to the task manager

#### 2. Task Client (taskclient/)
Task clients poll the control plane for tasks and dispatch them to deployer services:
```go
func (client *Client) runTask(taskToRun *task.TaskInfo) {
	client.taskTracker.AddRunningTask(taskToRun)
	defer client.taskTracker.RemoveRunningTask(taskToRun)

	output, err := client.workerClient.RunTask(context.Background(), &task.RunTaskRequest{
		TaskInfo: taskToRun,
	})
	// ... handle response
}
```

#### 3. Kubernetes Deployer Service (cloud-k8s-service/)
The KubernetesService handles EKS cluster provisioning:
```go
func (ks *KubernetesService) CreateUpdate(ctx context.Context, req *deployer.KubernetesServiceCreateUpdateRequest) (*deployer.KubernetesServiceCreateUpdateResponse, error) {
	tfStack, err := ks.makeTFStackFromKubernetesRequest(
		ctx,
		logger,
		req.GetKubernetes(),
		req.GetAccessSpec(),
	)
	// ...
	err = tfStack.Apply(ctx)  // Execute Terraform
	// ...
	// Install AWS Add-ons (storage class, LB controller, Karpenter)
	if kubernetes.Spec.CloudType == entity.CloudType_CLOUD_TYPE_AWS {
		err = awsPkg.InstallAddOns(ctx, awsTfOutput, awsCreds.Credentials, kubernetes)
	}
}
```

#### 4 Terraform Stack & Driver (Execution Engine)
The utils/terraform package provides the abstraction for running terraform:
```go
type Driver interface {
	Apply(context.Context) error
	Destroy(context.Context) error
	Output(context.Context) ([]byte, error)
	Plan(ctx context.Context, planUID string) ([]byte, error)
	Close() error
}
```
The execution flow in the driver is as follows:
```go
func (d *driver) Apply(ctx context.Context) error {
	args := []string{"apply", "-auto-approve", "-input=false"}
	if !d.opts.Colorize {
		args = append(args, "-no-color")
	}
	args = append(args, d.opts.VarArgs...)
	cmd := buildTerraformCmd(ctx, d.opts, args...)
	return d.initAndCommand(ctx, cmd)
}
```
Where initAndCommand runs terraform init first, then the actual command:
```go
func (d *driver) initAndCommand(ctx context.Context, cmd *exec.Cmd) error {
	if err := d.init(ctx); err != nil {
		return err
	}
	return runTerraformCmd(ctx, d.opts, cmd)
}
```

#### 5 Terraform Configuration Management
Terraform configs are organized by cloud type and infra version:
```yaml
cloud-network-service/terraform/
├── aws/
│   ├── v2.0.0/
│   ├── v2.1.0/
│   ├── v2.2.0/
│   └── v2.3.0/
├── azure/
│   └── v2.0.0/ ... v3.0.0/
└── gcp/
    └── v2.2.0/
```
The TFConfigs struct maps entity cloud type and version to the correct terraform binary and config path:
```go
func (tfc *TFConfigs) PathArgs(cloud entity.CloudType,
	currInfraVersion string) (*TFPathArgs, error) {
	// ... determines infra version and terraform version
	return &TFPathArgs{
		TFPath:       filepath.Join(tfc.TFBinDir, tfBinary),        // e.g., terraform-v1.8.3
		TFConfigPath: filepath.Join(tfc.TFConfigDir, cloudName, infraVersion), // e.g., aws/v2.3.0
		InfraVersion: infraVersion,
		TFVersion:    tfVersion,
	}, nil
}
```

### Provisioning workflow for AWS Kubernetes
The general workflow is as follows:
```yaml
┌─────────────────┐     ┌──────────────────┐     ┌───────────────────┐
│   Controlplane  │────▶│   Task Manager   │────▶│  Cloud Service    │
│   Controller    │     │   (GetTasks)     │     │  (k8s/network/..) │
└─────────────────┘     └──────────────────┘     └───────────────────┘
        │                                                 │
        │ Creates tasks for                               │
        │ entity state changes                            ▼
        │                                        ┌───────────────────┐
        │                                        │  TF Stack/Driver  │
        │                                        │  - init           │
        │                                        │  - apply/destroy  │
        │                                        │  - output         │
        │                                        └───────────────────┘
        │                                                 │
        │                                                 ▼
        │                                        ┌───────────────────┐
        │                                        │  TF Provider      │
        │                                        │  - VarArgs()      │
        │                                        │  - BackendArgs()  │
        │                                        │  - EnvArgs()      │
        │                                        └───────────────────┘
        │                                                 │
        │                                                 ▼
        │                                        ┌───────────────────┐
        │                                        │  Terraform CLI    │
        │                                        │  exec.Command()   │
        │                                        └───────────────────┘
        │                                                 │
        │                                                 ▼
        │                                        ┌───────────────────┐
        ▼                                        │  .tf files        │
┌─────────────────┐                              │  (aws/v2.3.0/...) │
│ Update entity   │◀─────────────────────────────│  + state backend  │
│ status in DB    │        Output parsed         └───────────────────┘
└─────────────────┘
```

Each cloud (AWS/Azure/GCP) has a provider that implements: 
```go
type ArgsProvider[E Entity] interface {
	ProviderBackend
	VarArgsProvider[E]
}

type Provider[E Entity, ES EntityStatus] interface {
	ArgsProvider[E]
	StatusUnmarshaler[E, ES]
}

type VarArgsProvider[E Entity] interface {
	VarArgs(E) ([]string, error)
	CredentialVarArgs(ctx context.Context, access *entity.CloudAccess, entityId string) ([]string, error)
}
```
For example, AWS implements VarArgs for network:
```go
func (p *tfProvider) VarArgs(network *entity.Network) ([]string, error) {
	// ... converts entity fields to terraform variables
	return []string{
		common.JoinWithEquals(tfaws.VarAwsRegion, network.Spec.Region),
		common.JoinWithEquals(tfaws.VarAwsVpcName, network.Metadata.Name),
		common.JoinWithEquals(tfaws.VarAwsCidrRange, network.Spec.Cidr),
		// ... more variables
	}, nil
}
```

#### 1: Network (VPC) Provisioning
The cloud-network-service provisions the underlying VPC infrastructure first:
```go
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "5.1.1"

  name                 = var.vpc_name
  cidr                 = var.cidr_range
  azs                  = var.aws_azs
  private_subnets      = var.aws_private_subnet_cidrs
  public_subnets       = var.aws_public_subnet_cidrs
  intra_subnets        = var.aws_eks_controlplane_subnet_cidrs
  enable_dns_hostnames = true
  enable_nat_gateway   = true
  // ...
}
```
In this function, it creates following resources:
1. VPC with configurable CIDR range
2. Public subnets (for load balancers)
3. Private subnets (for worker nodes)
4. Intra subnets (for EKS control plane ENIs)
5. NAT Gateways (one per AZ)
6. Elastic IPs for NAT and ELB
7. S3 VPC Endpoint
8. Network ACLs

#### 2: EKS Cluster Provisioning
The cloud-k8s-service provisions the Kubernetes cluster using the official terraform-aws-modules/eks/aws module:
```tf
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 19.1"

  cluster_name                         = var.cluster_name
  cluster_version                      = var.cluster_version
  cluster_endpoint_public_access       = var.public_access
  cluster_endpoint_public_access_cidrs = var.public_access_cidrs

  vpc_id     = var.vpc_id
  subnet_ids = concat(var.private_subnet_ids, var.public_subnet_ids)
  control_plane_subnet_ids = var.controlplane_subnet_ids

  cluster_addons = local.modified_cluster_addons

  eks_managed_node_groups = {
    default_node_group = { /* ... */ }
  }
  // ...
}
```
In this step, it creates resources:
1. EKS Cluster with specified Kubernetes version
2. OIDC Identity Provider (for IRSA)
3. Default managed node group (Bottlerocket AMI)
4. Additional managed node groups per availability zone
5. IAM roles for:
   EKS cluster
   Node groups
6. AWS Load Balancer Controller
7. Karpenter (if enabled)
8. KMS key for secrets encryption
9. EKS addons: vpc-cni, coredns, kube-proxy, aws-ebs-csi-driver

#### 3: Post-Terraform Add-ons
After Terraform completes, the service installs additional components via Kubernetes APIs:
```go
func InstallAddOns(ctx context.Context, result AwsTfOutput, credentials *entity.AwsCredentials, kubernetes *entity.Kubernetes) error {
	// Generate kubeconfig using EKS token
	eksToken, err := eksProvider.GenerateToken(ctx, awsCredentials, result.KubernetesClusterName.Value.(string))
	kubeConfig, err := awsInfra.GenerateKubeConfigFile(/* ... */)

	// 1. Install Storage Class
	err = installStorageClass(ctx, logger, kubeClient, kubernetes)

	// 2. Install AWS Load Balancer Controller (via Helm)
	err = installLbControllerAddOn(result, logger, kubeConfig, kubeClient)

	// 3. Install Karpenter (if enabled)
	if kubernetes.Spec.AwsKubernetesSpec.Karpenter != nil && kubernetes.Spec.AwsKubernetesSpec.Karpenter.Enabled {
		karp.KarpenterInstallation(ctx, kubernetes)
	}

	// 4. Configure Pod Identities
	podIdentityClient.ConfigurePodIdentities(ctx)
}
```
