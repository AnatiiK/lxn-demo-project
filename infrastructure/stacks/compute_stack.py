"""
ComputeStack - "Containers & Orchestration" talking point.
Runs the Dockerized app on ECS Fargate behind an ALB, with the WAF from
SecurityStack attached, and an encrypted S3 bucket for app data.

IAM roles are created HERE, not in SecurityStack - co-locating roles with
the resources that grant them permissions avoids a cross-stack circular
dependency (see the note in security_stack.py for the full explanation).
"""
from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_elasticloadbalancingv2 as elbv2,
    aws_s3 as s3,
    aws_wafv2 as wafv2,
    aws_iam as iam,
)
from constructs import Construct


class ComputeStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        vpc: ec2.Vpc,
        alb_security_group: ec2.SecurityGroup,
        service_security_group: ec2.SecurityGroup,
        kms_key,
        web_acl_arn: str,
        repository_uri: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- S3 bucket: KMS-encrypted, lifecycle policy ---
        self.data_bucket = s3.Bucket(
            self,
            "AppDataBucket",
            encryption=s3.BucketEncryption.KMS,
            encryption_key=kms_key,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            versioned=True,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="TransitionAndExpire",
                    transitions=[
                        s3.Transition(
                            storage_class=s3.StorageClass.INFREQUENT_ACCESS,
                            transition_after=Duration.days(30),
                        ),
                    ],
                    expiration=Duration.days(365),
                )
            ],
            removal_policy=RemovalPolicy.DESTROY,  # demo project only
            auto_delete_objects=True,  # demo project only
        )

        # --- IAM: ECS execution role (what ECS itself needs) ---
        execution_role = iam.Role(
            self,
            "EcsExecutionRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AmazonECSTaskExecutionRolePolicy"
                )
            ],
        )

        # --- IAM: ECS task role (what the APPLICATION CODE can do) ---
        task_role = iam.Role(
            self,
            "EcsTaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            description="Least-privilege role for the running application code",
        )
        task_role.add_to_policy(
            iam.PolicyStatement(
                sid="AllowKmsDecryptOnlyThisKey",
                actions=["kms:Decrypt", "kms:GenerateDataKey"],
                resources=[kms_key.key_arn],
            )
        )
        task_role.add_to_policy(
            iam.PolicyStatement(
                sid="AllowAppBucketReadWrite",
                actions=["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
                resources=[self.data_bucket.bucket_arn, f"{self.data_bucket.bucket_arn}/*"],
            )
        )

        # --- ECS cluster + Fargate service ---
        self.cluster = ecs.Cluster(self, "Cluster", vpc=vpc, container_insights=True)
        cluster = self.cluster

        task_def = ecs.FargateTaskDefinition(
    self,
    "TaskDef",
    cpu=256,
    memory_limit_mib=512,
    task_role=task_role,
    execution_role=execution_role,
    runtime_platform=ecs.RuntimePlatform(
        cpu_architecture=ecs.CpuArchitecture.ARM64,
        operating_system_family=ecs.OperatingSystemFamily.LINUX,
    ),
)

        # Using from_registry() with the URI string (not from_ecr_repository())
        # deliberately - avoids CDK auto-attaching a repo-specific grant that
        # would create a circular stack dependency. AmazonECSTaskExecutionRolePolicy
        # already covers ECR pull permissions generically.
        container = task_def.add_container(
            "AppContainer",
            image=ecs.ContainerImage.from_registry(f"{repository_uri}:latest"),
            logging=ecs.LogDrivers.aws_logs(stream_prefix="lxn-demo-app"),
            environment={"APP_BUCKET_NAME": self.data_bucket.bucket_name},
        )
        container.add_port_mappings(ecs.PortMapping(container_port=8080))

        self.service = ecs.FargateService(
            self,
            "Service",
            cluster=cluster,
            task_definition=task_def,
            desired_count=2,
            security_groups=[service_security_group],
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
        )

        scaling = self.service.auto_scale_task_count(min_capacity=2, max_capacity=6)
        scaling.scale_on_cpu_utilization(
            "CpuScaling",
            target_utilization_percent=60,
            scale_in_cooldown=Duration.seconds(60),
            scale_out_cooldown=Duration.seconds(60),
        )

        # --- ALB, public-facing ---
        self.alb = elbv2.ApplicationLoadBalancer(
            self,
            "Alb",
            vpc=vpc,
            internet_facing=True,
            security_group=alb_security_group,
        )
        listener = self.alb.add_listener("HttpListener", port=80, open=True)
        self.target_group = listener.add_targets(
            "EcsTarget",
            port=8080,
            targets=[self.service],
            health_check=elbv2.HealthCheck(
                path="/health",
                healthy_http_codes="200",
                interval=Duration.seconds(30),
                timeout=Duration.seconds(5),
            ),
        )

        wafv2.CfnWebACLAssociation(
            self,
            "WebAclAssociation",
            resource_arn=self.alb.load_balancer_arn,
            web_acl_arn=web_acl_arn,
        )
