#!/usr/bin/env python3
import aws_cdk as cdk
from stacks.network_stack import NetworkStack
from stacks.security_stack import SecurityStack
from stacks.ecr_stack import EcrStack
from stacks.compute_stack import ComputeStack
from stacks.guardduty_stack import GuardDutyStack
from stacks.cloudtrail_stack import CloudTrailStack
from stacks.observability_stack import ObservabilityStack
from stacks.github_oidc_stack import GithubOidcStack

app = cdk.App()

env = cdk.Environment(
    account=app.node.try_get_context("account"),
    region=app.node.try_get_context("region"),
)

network = NetworkStack(app, "LxnDemo-Network", env=env)
security = SecurityStack(app, "LxnDemo-Security", env=env)
ecr_stack = EcrStack(app, "LxnDemo-Ecr", env=env)

compute = ComputeStack(
    app, "LxnDemo-Compute",
    vpc=network.vpc,
    alb_security_group=network.alb_security_group,
    service_security_group=network.service_security_group,
    kms_key=security.kms_key,
    web_acl_arn=security.web_acl.attr_arn,
    repository_uri=ecr_stack.repository.repository_uri,
    env=env,
)
compute.add_dependency(network)
compute.add_dependency(security)
compute.add_dependency(ecr_stack)

GuardDutyStack(app, "LxnDemo-GuardDuty", env=env)
CloudTrailStack(app, "LxnDemo-CloudTrail", env=env)

observability = ObservabilityStack(
    app, "LxnDemo-Observability",
    ecs_service=compute.service, alb=compute.alb, target_group=compute.target_group,
    env=env,
)
observability.add_dependency(compute)

# NOTE: replace "AnatiiK/lxn-demo-project" below with your actual GitHub
# owner/repo once created in step 3 - must match exactly.
github_oidc = GithubOidcStack(
    app, "LxnDemo-GithubOidc",
    github_repo="AnatiiK/lxn-demo-project",
    ecr_repository_arn=ecr_stack.repository.repository_arn,
    ecs_service_arn=compute.service.service_arn,
    env=env,
)
github_oidc.add_dependency(ecr_stack)
github_oidc.add_dependency(compute)

app.synth()
