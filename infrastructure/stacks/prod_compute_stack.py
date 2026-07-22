"""
ProdComputeStack - genuine blue/green deployment via AWS CodeDeploy.

Shares the existing VPC, ECS cluster, and ALB with the Dev/Test service in
ComputeStack (a new listener on port 8080) rather than provisioning a
second ALB - a deliberate demo-scope cost tradeoff. Real multi-environment
setups typically use separate ALBs/domains per environment.
"""
from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_elasticloadbalancingv2 as elbv2,
    aws_iam as iam,
    aws_codedeploy as codedeploy,
    aws_sns as sns,
)
from constructs import Construct


class ProdComputeStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        vpc: ec2.Vpc,
        cluster: ecs.Cluster,
        alb: elbv2.ApplicationLoadBalancer,
        service_security_group: ec2.SecurityGroup,
        kms_key,
        repository_uri: str,
        data_bucket,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- IAM: same least-privilege split as Dev, separate role instances ---
        execution_role = iam.Role(
            self, "ProdEcsExecutionRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AmazonECSTaskExecutionRolePolicy"
                )
            ],
        )
        task_role = iam.Role(
            self, "ProdEcsTaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            description="Least-privilege role for the Prod application code",
        )
        task_role.add_to_policy(iam.PolicyStatement(
            sid="AllowKmsDecryptOnlyThisKey",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[kms_key.key_arn],
        ))
        task_role.add_to_policy(iam.PolicyStatement(
            sid="AllowAppBucketReadWrite",
            actions=["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
            resources=[data_bucket.bucket_arn, f"{data_bucket.bucket_arn}/*"],
        ))

        # --- Task definition ---
        task_def = ecs.FargateTaskDefinition(
            self, "ProdTaskDef",
            cpu=256, memory_limit_mib=512,
            task_role=task_role, execution_role=execution_role,
            runtime_platform=ecs.RuntimePlatform(
                cpu_architecture=ecs.CpuArchitecture.ARM64,
                operating_system_family=ecs.OperatingSystemFamily.LINUX,
            ),
        )
        container = task_def.add_container(
            "AppContainer",
            image=ecs.ContainerImage.from_registry(f"{repository_uri}:latest"),
            logging=ecs.LogDrivers.aws_logs(stream_prefix="lxn-demo-prod"),
            environment={"APP_BUCKET_NAME": data_bucket.bucket_name, "ENVIRONMENT": "prod"},
        )
        container.add_port_mappings(ecs.PortMapping(container_port=8080))

        # --- Two target groups: Blue (live) and Green (next deploy target) ---
        self.blue_target_group = elbv2.ApplicationTargetGroup(
            self, "ProdBlueTG", vpc=vpc, port=8080,
            protocol=elbv2.ApplicationProtocol.HTTP,
            target_type=elbv2.TargetType.IP,
            health_check=elbv2.HealthCheck(path="/health", healthy_http_codes="200"),
        )
        self.green_target_group = elbv2.ApplicationTargetGroup(
            self, "ProdGreenTG", vpc=vpc, port=8080,
            protocol=elbv2.ApplicationProtocol.HTTP,
            target_type=elbv2.TargetType.IP,
            health_check=elbv2.HealthCheck(path="/health", healthy_http_codes="200"),
        )

        # --- Prod listener on the SAME ALB, port 8080 ---
        self.prod_listener = elbv2.ApplicationListener(
            self, "ProdListener",
            load_balancer=alb,
            port=8080,
            protocol=elbv2.ApplicationProtocol.HTTP,
            default_target_groups=[self.blue_target_group],
        )

        # --- ECS service - CODE_DEPLOY controller hands traffic-shifting
        # control to CodeDeploy instead of ECS's own rolling update logic.
        # Set at creation, can't be changed on an existing service. ---
        self.service = ecs.FargateService(
            self, "ProdService",
            cluster=cluster, task_definition=task_def, desired_count=2,
            security_groups=[service_security_group],
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            deployment_controller=ecs.DeploymentController(
                type=ecs.DeploymentControllerType.CODE_DEPLOY
            ),
        )
        self.blue_target_group.add_target(self.service)

        # --- SNS: deployment success/failure notifications ---
        self.deploy_alerts_topic = sns.Topic(
            self, "ProdDeployAlerts", display_name="lxn-demo-prod-deploy-alerts"
        )

        # --- CodeDeploy: the actual blue/green orchestrator ---
        codedeploy_app = codedeploy.EcsApplication(self, "ProdCodeDeployApp")

        self.deployment_group = codedeploy.EcsDeploymentGroup(
            
            self, "ProdDeploymentGroup",
            application=codedeploy_app,
            service=self.service,
            deployment_config=codedeploy.EcsDeploymentConfig.ALL_AT_ONCE,
            blue_green_deployment_config=codedeploy.EcsBlueGreenDeploymentConfig(
                blue_target_group=self.blue_target_group,
                green_target_group=self.green_target_group,
                listener=self.prod_listener,
            ),
            auto_rollback=codedeploy.AutoRollbackConfig(failed_deployment=True),
        )

        # Wire SNS to CodeDeploy's own lifecycle events - success AND
        # failure, so an approver/on-call knows either way.
        cfn_dg = self.deployment_group.node.default_child
        cfn_dg.trigger_configurations = [{
            "triggerName": "ProdDeployNotifications",
            "triggerTargetArn": self.deploy_alerts_topic.topic_arn,
            "triggerEvents": ["DeploymentSuccess", "DeploymentFailure"],
        }]
        self.deploy_alerts_topic.grant_publish(
            iam.ServicePrincipal("codedeploy.amazonaws.com")
        )

        # Expose for GithubOidcStack to grant scoped permissions against
        self.execution_role = execution_role
        self.task_role = task_role
        self.codedeploy_application = codedeploy_app
