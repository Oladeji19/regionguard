from __future__ import annotations

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import (
    aws_apigateway as apigateway,
)
from aws_cdk import (
    aws_cloudwatch as cloudwatch,
)
from aws_cdk import (
    aws_cloudwatch_actions as cloudwatch_actions,
)
from aws_cdk import (
    aws_dynamodb as dynamodb,
)
from aws_cdk import (
    aws_iam as iam,
)
from aws_cdk import (
    aws_kms as kms,
)
from aws_cdk import (
    aws_lambda as lambda_,
)
from aws_cdk import (
    aws_lambda_event_sources as lambda_event_sources,
)
from aws_cdk import (
    aws_logs as logs,
)
from aws_cdk import (
    aws_sns as sns,
)
from aws_cdk import (
    aws_sns_subscriptions as subscriptions,
)
from aws_cdk import (
    aws_sqs as sqs,
)
from aws_cdk import (
    aws_stepfunctions as stepfunctions,
)
from aws_cdk import (
    aws_stepfunctions_tasks as tasks,
)
from constructs import Construct


class RegionGuardStack(Stack):
    """Serverless monitoring and automated-remediation infrastructure."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        incidents = dynamodb.Table(
            self,
            "Incidents",
            partition_key=dynamodb.Attribute(
                name="event_id",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            time_to_live_attribute="expires_at",
            removal_policy=RemovalPolicy.DESTROY,
        )

        incidents.add_global_secondary_index(
            index_name="service-observed-at-index",
            partition_key=dynamodb.Attribute(
                name="service_key",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="observed_at",
                type=dynamodb.AttributeType.STRING,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        dead_letter_queue = sqs.Queue(
            self,
            "HealthEventsDlq",
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            retention_period=Duration.days(14),
        )
        health_events = sqs.Queue(
            self,
            "HealthEvents",
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            visibility_timeout=Duration.seconds(90),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=dead_letter_queue,
            ),
        )

        sns_key = kms.Alias.from_alias_name(self, "AwsManagedSnsKey", "alias/aws/sns")
        alerts = sns.Topic(
            self,
            "OperationsAlerts",
            display_name="RegionGuard Operations Alerts",
            master_key=sns_key,
        )
        notification_email = self.node.try_get_context("notificationEmail")
        if notification_email:
            alerts.add_subscription(subscriptions.EmailSubscription(notification_email))

        shared_lambda_config = {
            "runtime": lambda_.Runtime.PYTHON_3_12,
            "architecture": lambda_.Architecture.X86_64,
            "code": lambda_.Code.from_asset("lambda_src"),
            "memory_size": 256,
            "timeout": Duration.seconds(30),
            "tracing": lambda_.Tracing.ACTIVE,
        }

        def lambda_log_group(construct_id: str, suffix: str) -> logs.LogGroup:
            return logs.LogGroup(
                self,
                construct_id,
                log_group_name=f"/aws/lambda/{self.stack_name}-{suffix}",
                retention=logs.RetentionDays.ONE_WEEK,
                removal_policy=RemovalPolicy.DESTROY,
            )

        ingest_function = lambda_.Function(
            self,
            "IngestFunction",
            handler="ingest.app.handler",
            environment={"QUEUE_URL": health_events.queue_url},
            log_group=lambda_log_group("IngestLogs", "ingest"),
            **shared_lambda_config,
        )
        health_events.grant_send_messages(ingest_function)

        remediator_function = lambda_.Function(
            self,
            "RemediatorFunction",
            handler="remediator.app.handler",
            environment={
                "INCIDENTS_TABLE": incidents.table_name,
                "METRIC_NAMESPACE": "RegionGuard",
            },
            log_group=lambda_log_group("RemediatorLogs", "remediator"),
            **shared_lambda_config,
        )
        incidents.grant_read_write_data(remediator_function)
        remediator_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],
                conditions={"StringEquals": {"cloudwatch:namespace": "RegionGuard"}},
            )
        )

        remediation_task = tasks.LambdaInvoke(
            self,
            "ExecuteRemediation",
            lambda_function=remediator_function,
            payload=stepfunctions.TaskInput.from_json_path_at("$"),
            payload_response_only=True,
        )

        success_notification = tasks.SnsPublish(
            self,
            "PublishRecoverySuccess",
            topic=alerts,
            subject="RegionGuard service recovered",
            message=stepfunctions.TaskInput.from_json_path_at("$"),
        )
        failure_notification = tasks.SnsPublish(
            self,
            "PublishRecoveryFailure",
            topic=alerts,
            subject="RegionGuard recovery failed",
            message=stepfunctions.TaskInput.from_json_path_at("$"),
        )

        definition = (
            stepfunctions.Wait(
                self,
                "RecoveryBackoff",
                time=stepfunctions.WaitTime.duration(Duration.seconds(5)),
            )
            .next(remediation_task)
            .next(
                stepfunctions.Choice(self, "RecoverySucceeded")
                .when(
                    stepfunctions.Condition.boolean_equals("$.recovery_success", True),
                    success_notification,
                )
                .otherwise(failure_notification)
            )
        )

        workflow_logs = logs.LogGroup(
            self,
            "RemediationWorkflowLogs",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )
        remediation_workflow = stepfunctions.StateMachine(
            self,
            "RemediationWorkflow",
            definition_body=stepfunctions.DefinitionBody.from_chainable(definition),
            timeout=Duration.minutes(2),
            tracing_enabled=True,
            logs=stepfunctions.LogOptions(
                destination=workflow_logs,
                level=stepfunctions.LogLevel.ALL,
                include_execution_data=True,
            ),
        )

        processor_function = lambda_.Function(
            self,
            "ProcessorFunction",
            handler="processor.app.handler",
            environment={
                "INCIDENTS_TABLE": incidents.table_name,
                "STATE_MACHINE_ARN": remediation_workflow.state_machine_arn,
                "METRIC_NAMESPACE": "RegionGuard",
            },
            log_group=lambda_log_group("ProcessorLogs", "processor"),
            reserved_concurrent_executions=10,
            **shared_lambda_config,
        )
        incidents.grant_read_write_data(processor_function)
        remediation_workflow.grant_start_execution(processor_function)
        processor_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],
                conditions={"StringEquals": {"cloudwatch:namespace": "RegionGuard"}},
            )
        )
        processor_function.add_event_source(
            lambda_event_sources.SqsEventSource(
                health_events,
                batch_size=10,
                report_batch_item_failures=True,
            )
        )

        status_function = lambda_.Function(
            self,
            "StatusFunction",
            handler="status.app.handler",
            environment={"INCIDENTS_TABLE": incidents.table_name},
            log_group=lambda_log_group("StatusLogs", "status"),
            **shared_lambda_config,
        )
        incidents.grant_read_data(status_function)

        api = apigateway.RestApi(
            self,
            "RegionGuardApi",
            rest_api_name="RegionGuard API",
            description="Health event ingestion and incident status API",
            deploy_options=apigateway.StageOptions(
                stage_name="prod",
                logging_level=apigateway.MethodLoggingLevel.INFO,
                data_trace_enabled=False,
                metrics_enabled=True,
                throttling_rate_limit=25,
                throttling_burst_limit=50,
            ),
            cloud_watch_role=True,
        )

        health = api.root.add_resource("health")
        health.add_method(
            "POST",
            apigateway.LambdaIntegration(ingest_function),
            authorization_type=apigateway.AuthorizationType.IAM,
        )
        incidents_resource = api.root.add_resource("incidents")
        incidents_resource.add_method(
            "GET",
            apigateway.LambdaIntegration(status_function),
            authorization_type=apigateway.AuthorizationType.IAM,
        )

        unhealthy_metric = cloudwatch.Metric(
            namespace="RegionGuard",
            metric_name="UnhealthyEvents",
            statistic="Sum",
            period=Duration.minutes(1),
        )
        unhealthy_alarm = cloudwatch.Alarm(
            self,
            "UnhealthyServiceAlarm",
            metric=unhealthy_metric,
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description="A service reported an unhealthy health event",
        )
        unhealthy_alarm.add_alarm_action(cloudwatch_actions.SnsAction(alerts))

        dlq_alarm = cloudwatch.Alarm(
            self,
            "DeadLetterQueueAlarm",
            metric=dead_letter_queue.metric_approximate_number_of_messages_visible(),
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description="A health event could not be processed after three attempts",
        )
        dlq_alarm.add_alarm_action(cloudwatch_actions.SnsAction(alerts))

        dashboard = cloudwatch.Dashboard(
            self,
            "OperationsDashboard",
            dashboard_name="RegionGuard-Operations",
        )
        dashboard.add_widgets(
            cloudwatch.GraphWidget(
                title="Service Health Events",
                left=[
                    unhealthy_metric,
                    cloudwatch.Metric(
                        namespace="RegionGuard",
                        metric_name="HealthyEvents",
                        statistic="Sum",
                        period=Duration.minutes(1),
                    ),
                    cloudwatch.Metric(
                        namespace="RegionGuard",
                        metric_name="DegradedEvents",
                        statistic="Sum",
                        period=Duration.minutes(1),
                    ),
                ],
            ),
            cloudwatch.GraphWidget(
                title="Recovery Time",
                left=[
                    cloudwatch.Metric(
                        namespace="RegionGuard",
                        metric_name="RecoveryTimeMs",
                        statistic="Average",
                        period=Duration.minutes(1),
                    )
                ],
            ),
            cloudwatch.GraphWidget(
                title="Queue Depth",
                left=[
                    health_events.metric_approximate_number_of_messages_visible(),
                    dead_letter_queue.metric_approximate_number_of_messages_visible(),
                ],
            ),
            cloudwatch.GraphWidget(
                title="Lambda Errors",
                left=[
                    ingest_function.metric_errors(),
                    processor_function.metric_errors(),
                    remediator_function.metric_errors(),
                    status_function.metric_errors(),
                ],
            ),
        )

        CfnOutput(self, "ApiUrl", value=api.url)
        CfnOutput(self, "HealthEventsQueueUrl", value=health_events.queue_url)
        CfnOutput(self, "DeadLetterQueueUrl", value=dead_letter_queue.queue_url)
        CfnOutput(self, "IncidentsTableName", value=incidents.table_name)
        CfnOutput(self, "AlertsTopicArn", value=alerts.topic_arn)
        CfnOutput(self, "RemediationWorkflowArn", value=remediation_workflow.state_machine_arn)
        CfnOutput(self, "DashboardName", value=dashboard.dashboard_name)
