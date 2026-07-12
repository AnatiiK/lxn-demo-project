"""
GithubOidcStack - lets GitHub Actions assume an AWS role using short-lived
OIDC tokens instead of storing long-lived AWS access keys as GitHub secrets.
Same "no static credentials for automation" principle applied locally
(aws login + a narrowly scoped static profile), applied here to the
pipeline itself. Permissions are deliberately narrow: push to one ECR
repo, restart one ECS service - nothing IAM/network/security-group related.
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
                    # Scoped to main branch only - matches the workflow's
                    # own trigger, tighter than a blanket wildcard.
                    "StringLike": {"token.actions.githubusercontent.com:sub": f"repo:{github_repo}:ref:refs/heads/main"},
                },
                assume_role_action="sts:AssumeRoleWithWebIdentity",
            ),
            description="Assumed by GitHub Actions via OIDC - no static AWS keys stored in the repo",
        )

        self.role.add_to_policy(iam.PolicyStatement(
            actions=["ecr:GetAuthorizationToken"],
            resources=["*"],  # this specific action doesn't support resource-level scoping
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
        self.role.add_to_policy(iam.PolicyStatement(
            actions=["ecs:UpdateService", "ecs:DescribeServices"],
            resources=[ecs_service_arn],
        ))

        CfnOutput(self, "GithubActionsRoleArn", value=self.role.role_arn)
