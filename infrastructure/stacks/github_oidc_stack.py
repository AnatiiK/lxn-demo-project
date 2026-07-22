"""
GithubOidcStack - lets GitHub Actions assume an AWS role using short-lived
OIDC tokens instead of storing long-lived AWS access keys as GitHub secrets.
Permissions are scoped narrowly per environment: Dev gets a simple ECS
service update; Prod gets exactly what's needed to register a new task
definition and trigger a CodeDeploy blue/green deployment - nothing
IAM/network/security-group related beyond the two specific Prod roles
this pipeline needs to pass.
"""
from aws_cdk import Stack, aws_iam as iam, CfnOutput
from constructs import Construct


class GithubOidcStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        github_repo: str,
        ecr_repository_arn: str,
        ecs_service_arn: str,
        prod_ecs_service_arn: str,
        prod_execution_role_arn: str,
        prod_task_role_arn: str,
        prod_codedeploy_application_arn: str,
        prod_codedeploy_deployment_group_arn: str,
        prod_sns_topic_arn: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        provider = iam.OpenIdConnectProvider(
            self,
            "GithubOidcProvider",
            url="https://token.actions.githubusercontent.com",
            client_ids=["sts.amazonaws.com"],
        )

        self.role = iam.Role(
            self,
            "GithubActionsRole",
            assumed_by=iam.FederatedPrincipal(
                provider.open_id_connect_provider_arn,
                conditions={
                    "StringEquals": {"token.actions.githubusercontent.com:aud": "sts.amazonaws.com"},
                    "StringLike": {"token.actions.githubusercontent.com:sub": f"repo:{github_repo}:ref:refs/heads/main"},
                },
                assume_role_action="sts:AssumeRoleWithWebIdentity",
            ),
            description="Assumed by GitHub Actions via OIDC - no static AWS keys stored in the repo",
        )

        # --- ECR: shared by both Dev and Prod builds ---
        self.role.add_to_policy(iam.PolicyStatement(
            actions=["ecr:GetAuthorizationToken"],
            resources=["*"],  # doesn't support resource-level scoping
        ))
        self.role.add_to_policy(iam.PolicyStatement(
            actions=[
                "ecr:BatchCheckLayerAvailability", "ecr:PutImage",
                "ecr:InitiateLayerUpload", "ecr:UploadLayerPart",
                "ecr:CompleteLayerUpload", "ecr:GetDownloadUrlForLayer",
                "ecr:BatchGetImage",
            ],
            resources=[ecr_repository_arn],
        ))

        # --- Dev: simple rolling update, unchanged from before ---
        self.role.add_to_policy(iam.PolicyStatement(
            actions=["ecs:UpdateService", "ecs:DescribeServices"],
            resources=[ecs_service_arn],
        ))

        # --- Prod: register a new task definition ---
        # RegisterTaskDefinition doesn't support resource-level scoping -
        # the task definition doesn't exist yet at policy-evaluation time.
        self.role.add_to_policy(iam.PolicyStatement(
            actions=["ecs:RegisterTaskDefinition", "ecs:DescribeTaskDefinition"],
            resources=["*"],
        ))

        # --- Prod: pass the two Prod-specific roles to the new task def -
        # scoped to exactly these two ARNs, not a wildcard. This is the
        # permission that would matter most if this credential ever leaked -
        # it can only ever hand off these two specific, already-scoped roles.
        self.role.add_to_policy(iam.PolicyStatement(
            actions=["iam:PassRole"],
            resources=[prod_execution_role_arn, prod_task_role_arn],
        ))

        # --- Prod: describe the service (for render-task-definition action) ---
        self.role.add_to_policy(iam.PolicyStatement(
            actions=["ecs:DescribeServices"],
            resources=[prod_ecs_service_arn],
        ))

        # --- Prod: trigger and monitor the CodeDeploy blue/green deployment ---
        self.role.add_to_policy(iam.PolicyStatement(
            actions=[
                "codedeploy:CreateDeployment",
                "codedeploy:GetDeployment",
                "codedeploy:GetDeploymentGroup",
                "codedeploy:RegisterApplicationRevision",
                "codedeploy:GetApplicationRevision",
            ],
            resources=[prod_codedeploy_application_arn, prod_codedeploy_deployment_group_arn],
        ))
        # GetDeploymentConfig targets AWS's own managed config resources
        # (e.g. CodeDeployDefault.ECSAllAtOnce), not anything this project
        # owns - genuinely needs a broader resource match.
        self.role.add_to_policy(iam.PolicyStatement(
            actions=["codedeploy:GetDeploymentConfig"],
            resources=["*"],
        ))

        # --- Prod: publish the "Dev passed, awaiting your approval" notice ---
        self.role.add_to_policy(iam.PolicyStatement(
            actions=["sns:Publish"],
            resources=[prod_sns_topic_arn],
        ))

        CfnOutput(self, "GithubActionsRoleArn", value=self.role.role_arn)
