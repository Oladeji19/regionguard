import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

from regionguard.regionguard_stack import RegionGuardStack


def test_stack_contains_reliability_resources():
    app = cdk.App()
    stack = RegionGuardStack(app, "TestRegionGuardStack")
    template = Template.from_stack(stack)

    template.resource_count_is("AWS::DynamoDB::Table", 1)
    template.resource_count_is("AWS::SQS::Queue", 2)
    template.resource_count_is("AWS::Lambda::Function", 4)
    template.resource_count_is("AWS::StepFunctions::StateMachine", 1)
    template.resource_count_is("AWS::CloudWatch::Alarm", 2)
    template.has_resource_properties(
        "AWS::ApiGateway::Method",
        Match.object_like({"AuthorizationType": "AWS_IAM"}),
    )

