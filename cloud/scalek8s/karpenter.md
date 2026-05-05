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

resource "aws_autoscaling_group" "example_asg" {
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

We can define auto scaling policies on ASG. 

Here is a CPU-based scaling policy, which keeps average CPU around 50%, automatically scales out when CPU>50%, scales in when CPU<50%:
```yaml
resource "aws_autoscaling_policy" "cpu_targeted_policy" {
  name                   = "cpu-target-tracking"
  policy_type            = "TargetTrackingScaling"
  autoscaling_group_name = aws_autoscaling_group.example_asg.name

  target_tracking_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ASGAverageCPUUtilization"
    }
    target_value = 50.0
  }
}
```

It also supports more fine grained scaling policy, like step scaling. In this example, if CPU > 70%, add 1 instance. We can define multiple steps like: +1 instance at 70%, +3 instances at 90%.
```yaml
resource "aws_cloudwatch_metric_alarm" "high_cpu" {
  alarm_name          = "high-cpu"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/EC2"
  period              = 60
  statistic           = "Average"
  threshold           = 70

  dimensions = {
    AutoScalingGroupName = aws_autoscaling_group.example_asg.name
  }

  alarm_actions = [aws_autoscaling_policy.scale_out.arn]
}

resource "aws_autoscaling_policy" "scale_out" {
  name                   = "scale-out"
  policy_type            = "StepScaling"
  autoscaling_group_name = aws_autoscaling_group.example.name

  adjustment_type = "ChangeInCapacity"

  step_adjustment {
    metric_interval_lower_bound = 0
    scaling_adjustment          = 1
  }
}
```

## EKS node groups
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

## In-cluster autoscaling
Kubernetes provides a number of tools to help us manage our application deployment, including scaling.

### Horizontal pod autoscaler
In Kubernetes, a HorizontalPodAutoscaler (HPA) automatically updates a workload resource (such as a Deployment or StatefulSet), with the aim of automatically scaling capacity to match demand.

HPA respond to increased load by deploying more Pods, which is different from vertical scaling. Kubernetes would mean assigning more resources (for example: memory or CPU) to the Pods that are already running for the workload.

If the load decreases, and the number of Pods is above the configured minimum, HPA instructs the workload resource (the Deployment, StatefulSet, or other similar resource) to scale back down. HPA does not apply to objects that can't be scaled (for example: a DaemonSet.)

HPA is implemented as a Kubernetes API resource and a controller. The resource determines the behavior of the controller. The HPA controller, running within the Kubernetes control plane, periodically adjusts the desired scale of its target (for example, a Deployment) to match observed metrics such as average CPU utilization, average memory utilization, or any other custom metric you specify.

### Vertical Pod Autoscaling
In Kubernetes, a VerticalPodAutoscaler (VPA) automatically updates a workload management resource (such as a Deployment or StatefulSet), with the aim of automatically adjusting infrastructure resource requests and limits to match actual usage.

VPA responds to increased resource demand by assigning more resources (for example: memory or CPU) to the Pods that are already running for the workload. This is also known as rightsizing, or sometimes autopilot. This is different from horizontal scaling, which for Kubernetes would mean deploying more Pods to distribute the load.

If the resource usage decreases, and the Pod resource requests are above optimal levels, the VPA instructs the workload resource (the Deployment, StatefulSet, or other similar resource) to adjust resource requests back down, preventing resource waste.

VPA is implemented as a Kubernetes API resource and a controller. The resource determines the behavior of the controller. VPA controller, running within the Kubernetes data plane, periodically adjusts the resource requests and limits of its target (for example, a Deployment) based on analysis of historical resource utilization, the amount of resources available in the cluster, and real-time events such as out-of-memory (OOM) conditions.



