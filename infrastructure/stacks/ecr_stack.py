"""
EcrStack - the container registry the app image lives in.
Explicit repository_name + CfnOutput so the URI is always discoverable
by name rather than guessed from an unfiltered describe-repositories call
(which can return the CDK bootstrap's own asset-staging repo instead).
"""
from aws_cdk import Stack, aws_ecr as ecr, RemovalPolicy, CfnOutput
from constructs import Construct


class EcrStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.repository = ecr.Repository(
            self,
            "AppRepository",
            repository_name="lxn-demo-app",
            image_scan_on_push=True,
            removal_policy=RemovalPolicy.DESTROY,  # demo project only
        )

        CfnOutput(
            self,
            "RepositoryUri",
            value=self.repository.repository_uri,
            description="Push images here: docker push <this-value>:latest",
        )
