# Karpenter notes

## Autoscaling options

## AWS autoscaling groups
AWS Auto Scaling Groups (ASG) manage EC2 instances, which
1. defines launch templates specifying instance configuration, then
2. set scaling policies to adjust capacity
3. AWS EC2 scales based on the policies

```yaml
resource "aws_launch_template" "example" {
  name_prefix   = "example-"
  image_id      = "ami-123456"
  instance_type = "t3.medium"
}

resource "aws_autoscaling_group" "example" {
  desired_capacity = 3
  max_size         = 5
  min_size         = 1

  vpc_zone_identifier = ["subnet-abc", "subnet-def"]

  launch_template {
    id      = aws_launch_template.example.id
    version = "$Latest"
  }
}
```
For Kubernetes, we can't use ASG directly, instead we use node group built on top of ASG. AWS manages the underlying ASG for Amazon EKS clusters.
Node group integrates with Kubernetes:
1. joins cluster automatically
2. managed upgrades
3. health checks
4. Less flexible than raw ASG

```yaml
resource "aws_eks_node_group" "example_ng" {
  cluster_name    = "my-cluster"
  node_group_name = "workers"
  node_role_arn   = aws_iam_role.worker.arn
  subnet_ids      = ["subnet-abc", "subnet-def"]

  scaling_config {
    desired_size = 3
    max_size     = 6
    min_size     = 1
  }

  instance_types = ["t3.medium"]
}
```

## Cluster autoscaler

## 
