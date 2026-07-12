"""
GuardDutyStack - "GuardDuty alerting" talking point, literally.
Enables GuardDuty account-wide, then wires its findings through
EventBridge to an SNS topic so a finding actually alerts someone,
rather than just sitting unread in a console.
"""
from aws_cdk import Stack, aws_guardduty as guardduty, aws_sns as sns, aws_events as events, aws_events_targets as targets
from constructs import Construct


class GuardDutyStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- Enable GuardDuty for this account ---
        self.detector = guardduty.CfnDetector(
            self,
            "Detector",
            enable=True,
            finding_publishing_frequency="FIFTEEN_MINUTES",
        )

        # --- Where alerts go ---
        # Stand-in for PagerDuty/Slack/email in a real setup - a real
        # subscription (email/Slack webhook) would be added to this topic
        # via an account-specific integration, left out here since that's
        # personal contact info, not infrastructure config.
        self.alert_topic = sns.Topic(
            self, "GuardDutyAlerts", display_name="lxn-demo-guardduty-findings"
        )

        # --- Route GuardDuty findings to the topic via EventBridge ---
        # GuardDuty publishes findings as EventBridge events automatically -
        # no extra wiring needed on GuardDuty's side, just a rule to catch them.
        rule = events.Rule(
            self,
            "GuardDutyFindingRule",
            description="Routes all GuardDuty findings to SNS for alerting",
            event_pattern=events.EventPattern(
                source=["aws.guardduty"],
                detail_type=["GuardDuty Finding"],
            ),
        )
        rule.add_target(targets.SnsTopic(self.alert_topic))
