"""
ObservabilityStack - the "monitoring and incident response" talking point.
Alarms wired to SNS (stand-in for PagerDuty/Slack), plus one dashboard
covering the questions an on-call engineer asks first: is it up, is it
fast, is it erroring, is it scaling?
"""
from aws_cdk import (
    Stack,
    Duration,
    aws_cloudwatch as cw,
    aws_cloudwatch_actions as cw_actions,
    aws_sns as sns,
    aws_ecs as ecs,
    aws_elasticloadbalancingv2 as elbv2,
)
from constructs import Construct


class ObservabilityStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        ecs_service: ecs.FargateService,
        alb: elbv2.ApplicationLoadBalancer,
        target_group: elbv2.ApplicationTargetGroup,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        alert_topic = sns.Topic(self, "AlertTopic", display_name="lxn-demo-alerts")
        alarm_action = cw_actions.SnsAction(alert_topic)

        cpu_alarm = cw.Alarm(
            self,
            "HighCpuAlarm",
            metric=ecs_service.metric_cpu_utilization(period=Duration.minutes(5)),
            threshold=80,
            evaluation_periods=3,
            datapoints_to_alarm=2,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            alarm_description="ECS CPU > 80% for 2 of 3 periods - check for a runaway request or scale-out lag",
        )
        cpu_alarm.add_alarm_action(alarm_action)

        five_xx_metric = alb.metrics.http_code_target(
            elbv2.HttpCodeTarget.TARGET_5XX_COUNT, period=Duration.minutes(5)
        )
        five_xx_alarm = cw.Alarm(
            self,
            "Alb5xxAlarm",
            metric=five_xx_metric,
            threshold=10,
            evaluation_periods=1,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            alarm_description="More than 10 5xx responses in 5 minutes - customers are seeing errors now",
        )
        five_xx_alarm.add_alarm_action(alarm_action)

        unhealthy_alarm = cw.Alarm(
            self,
            "UnhealthyHostAlarm",
            metric=target_group.metrics.unhealthy_host_count(period=Duration.minutes(1)),
            threshold=1,
            evaluation_periods=2,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            alarm_description="One or more ECS tasks failing ALB health checks",
        )
        unhealthy_alarm.add_alarm_action(alarm_action)

        dashboard = cw.Dashboard(self, "Dashboard", dashboard_name="lxn-demo-service")
        dashboard.add_widgets(
            cw.GraphWidget(title="ECS CPU Utilization", left=[ecs_service.metric_cpu_utilization()]),
            cw.GraphWidget(title="ALB Requests & 5xx Errors", left=[alb.metrics.request_count()], right=[five_xx_metric]),
        )
        dashboard.add_widgets(
            cw.GraphWidget(title="ALB Target Response Time", left=[alb.metrics.target_response_time()]),
            cw.GraphWidget(
                title="Healthy vs Unhealthy Hosts",
                left=[target_group.metrics.healthy_host_count()],
                right=[target_group.metrics.unhealthy_host_count()],
            ),
        )
