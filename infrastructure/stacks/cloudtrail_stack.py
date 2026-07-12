"""
CloudTrailStack - the audit-trail half of the detection layer.
GuardDuty flags that something suspicious happened; this is what lets you
reconstruct exactly what happened, by whom, and in what order.
"""
from aws_cdk import Stack, RemovalPolicy, aws_s3 as s3, aws_cloudtrail as cloudtrail
from constructs import Construct


class CloudTrailStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        log_bucket = s3.Bucket(
            self,
            "TrailLogBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,  # demo project only
            auto_delete_objects=True,  # demo project only
        )

        self.trail = cloudtrail.Trail(
            self,
            "Trail",
            bucket=log_bucket,
            is_multi_region_trail=True,
            include_global_service_events=True,
            enable_file_validation=True,  # detects tampering with log files after the fact
        )
