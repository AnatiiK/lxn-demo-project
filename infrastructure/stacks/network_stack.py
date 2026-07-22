"""
NetworkStack — the "Cloud Infrastructure design" talking point.
VPC, public/private subnets, NAT gateway, and the two security groups
(ALB and ECS service) that later stacks will attach to.
"""
from aws_cdk import Stack, aws_ec2 as ec2
from constructs import Construct


class NetworkStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Single NAT gateway (not one per AZ) — a deliberate cost tradeoff
        # for this project. In a real production HA design you'd want one
        # NAT per AZ so a single AZ failure doesn't take down egress for
        # the others. Good thing to mention proactively in the interview.
        self.vpc = ec2.Vpc(
            self,
            "Vpc",
            ip_addresses=ec2.IpAddresses.cidr("10.20.0.0/16"),
            max_azs=2,
            nat_gateways=1,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="private-app",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
            ],
        )

        self.alb_security_group = ec2.SecurityGroup(
            self,
            "AlbSecurityGroup",
            vpc=self.vpc,
            description="ALB ingress from the internet",
            allow_all_outbound=True,
        )
        self.alb_security_group.add_ingress_rule(
            ec2.Peer.any_ipv4(), ec2.Port.tcp(8080),
            "Prod HTTP - demo shares one ALB across environments; real prod would use a separate ALB/domain"
        )
        self.alb_security_group.add_ingress_rule(
            ec2.Peer.any_ipv4(), ec2.Port.tcp(443), "HTTPS from internet"
        )

        self.service_security_group = ec2.SecurityGroup(
            self,
            "ServiceSecurityGroup",
            vpc=self.vpc,
            description="ECS tasks - ingress only from the ALB",
            allow_all_outbound=True,
        )
        self.service_security_group.add_ingress_rule(
            self.alb_security_group,
            ec2.Port.tcp(8080),
            "App traffic from ALB only",
        )