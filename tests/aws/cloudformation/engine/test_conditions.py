import os.path

import pytest

from localstack.testing.aws.util import is_aws_cloud
from localstack.testing.pytest import markers
from localstack.utils.files import load_file
from localstack.utils.strings import short_uid

THIS_DIR = os.path.dirname(__file__)


class TestCloudFormationConditions:
    @markers.aws.validated
    def test_simple_condition_evaluation_deploys_resource(
        self, aws_client, deploy_cfn_template, cleanups
    ):
        topic_name = f"test-topic-{short_uid()}"
        deployment = deploy_cfn_template(
            template_path=os.path.join(
                THIS_DIR, "../../templates/conditions/simple-condition.yaml"
            ),
            parameters={"OptionParameter": "option-a", "TopicName": topic_name},
        )
        # verify that CloudFormation includes the resource
        stack_resources = aws_client.cloudformation.describe_stack_resources(
            StackName=deployment.stack_id
        )
        assert stack_resources["StackResources"]

        # verify actual resource deployment
        assert [
            t
            for t in aws_client.sns.get_paginator("list_topics")
            .paginate()
            .build_full_result()["Topics"]
            if topic_name in t["TopicArn"]
        ]

    @markers.aws.validated
    def test_simple_condition_evaluation_doesnt_deploy_resource(
        self, aws_client, deploy_cfn_template, cleanups
    ):
        """Note: Conditions allow us to deploy stacks that won't actually contain any deployed resources"""
        topic_name = f"test-topic-{short_uid()}"
        deployment = deploy_cfn_template(
            template_path=os.path.join(
                THIS_DIR, "../../templates/conditions/simple-condition.yaml"
            ),
            parameters={"OptionParameter": "option-b", "TopicName": topic_name},
        )
        # verify that CloudFormation ignores the resource
        aws_client.cloudformation.describe_stack_resources(StackName=deployment.stack_id)

        # FIXME: currently broken in localstack
        # assert stack_resources['StackResources'] == []

        # verify actual resource deployment
        assert [
            t for t in aws_client.sns.list_topics()["Topics"] if topic_name in t["TopicArn"]
        ] == []

    @pytest.mark.parametrize(
        "should_set_custom_name",
        ["yep", "nope"],
    )
    @markers.aws.validated
    def test_simple_intrinsic_fn_condition_evaluation(
        self, aws_client, deploy_cfn_template, should_set_custom_name
    ):
        """
        Tests a simple Fn::If condition evaluation

        The conditional ShouldSetCustomName (yep | nope) switches between an autogenerated and a predefined name for the topic

        FIXME: this should also work with the simple-intrinsic-condition-name-conflict.yaml template where the ID of the condition and the ID of the parameter are the same(!).
            It is currently broken in LocalStack though
        """
        topic_name = f"test-topic-{short_uid()}"
        deployment = deploy_cfn_template(
            template_path=os.path.join(
                THIS_DIR, "../../templates/conditions/simple-intrinsic-condition.yaml"
            ),
            parameters={
                "TopicName": topic_name,
                "ShouldSetCustomName": should_set_custom_name,
            },
        )
        # verify that the topic has the correct name
        topic_arn = deployment.outputs["TopicArn"]
        if should_set_custom_name == "yep":
            assert topic_name in topic_arn
        else:
            assert topic_name not in topic_arn

    @markers.aws.validated
    @pytest.mark.skipif(condition=not is_aws_cloud(), reason="not supported yet")
    def test_dependent_ref(self, aws_client, snapshot):
        """
        Tests behavior of a stack with 2 resources where one depends on the other.
        The referenced resource won't be deployed due to its condition evaluating to false, so the ref can't be resolved.

        This immediately leads to an error.
        """
        topic_name = f"test-topic-{short_uid()}"
        ssm_param_name = f"test-param-{short_uid()}"

        stack_name = f"test-condition-ref-stack-{short_uid()}"
        changeset_name = "initial"
        with pytest.raises(aws_client.cloudformation.exceptions.ClientError) as e:
            aws_client.cloudformation.create_change_set(
                StackName=stack_name,
                ChangeSetName=changeset_name,
                ChangeSetType="CREATE",
                TemplateBody=load_file(
                    os.path.join(THIS_DIR, "../../templates/conditions/ref-condition.yaml")
                ),
                Parameters=[
                    {"ParameterKey": "TopicName", "ParameterValue": topic_name},
                    {"ParameterKey": "SsmParamName", "ParameterValue": ssm_param_name},
                    {"ParameterKey": "OptionParameter", "ParameterValue": "option-b"},
                ],
            )
        snapshot.match("dependent_ref_exc", e.value.response)

    @markers.aws.validated
    @pytest.mark.skipif(condition=not is_aws_cloud(), reason="not supported yet")
    def test_dependent_ref_intrinsic_fn_condition(self, aws_client, deploy_cfn_template):
        """
        Checks behavior of un-refable resources
        """
        topic_name = f"test-topic-{short_uid()}"
        ssm_param_name = f"test-param-{short_uid()}"

        deploy_cfn_template(
            template_path=os.path.join(
                THIS_DIR, "../../templates/conditions/ref-condition-intrinsic-condition.yaml"
            ),
            parameters={
                "TopicName": topic_name,
                "SsmParamName": ssm_param_name,
                "OptionParameter": "option-b",
            },
        )

    @markers.aws.validated
    @pytest.mark.skipif(condition=not is_aws_cloud(), reason="not supported yet")
    def test_dependent_ref_with_macro(
        self, aws_client, deploy_cfn_template, lambda_su_role, cleanups
    ):
        """
        specifying option-b would normally lead to an error without the macro because of the unresolved ref.
        Because the macro replaced the resources though, the test passes.
        We've therefore shown that conditions aren't fully evaluated before the transformations

        Related findings:
        * macros are not allowed to transform Parameters (macro invocation by CFn will fail in this case)

        """

        log_group_name = f"test-log-group-{short_uid()}"
        aws_client.logs.create_log_group(logGroupName=log_group_name)

        deploy_cfn_template(
            template_path=os.path.join(
                THIS_DIR, "../../templates/conditions/ref-condition-macro-def.yaml"
            ),
            parameters={
                "FnRole": lambda_su_role,
                "LogGroupName": log_group_name,
                "LogRoleARN": lambda_su_role,
            },
        )

        topic_name = f"test-topic-{short_uid()}"
        ssm_param_name = f"test-param-{short_uid()}"
        stack_name = f"test-condition-ref-macro-stack-{short_uid()}"
        changeset_name = "initial"
        cleanups.append(lambda: aws_client.cloudformation.delete_stack(StackName=stack_name))
        aws_client.cloudformation.create_change_set(
            StackName=stack_name,
            ChangeSetName=changeset_name,
            ChangeSetType="CREATE",
            TemplateBody=load_file(
                os.path.join(THIS_DIR, "../../templates/conditions/ref-condition-macro.yaml")
            ),
            Parameters=[
                {"ParameterKey": "TopicName", "ParameterValue": topic_name},
                {"ParameterKey": "SsmParamName", "ParameterValue": ssm_param_name},
                {"ParameterKey": "OptionParameter", "ParameterValue": "option-b"},
            ],
        )

        aws_client.cloudformation.get_waiter("change_set_create_complete").wait(
            ChangeSetName=changeset_name, StackName=stack_name
        )

    @pytest.mark.parametrize(
        ["env_type", "should_create_bucket", "should_create_policy"],
        [
            ("test", False, False),
            ("test", True, False),
            ("prod", False, False),
            ("prod", True, True),
        ],
        ids=[
            "test-nobucket-nopolicy",
            "test-bucket-nopolicy",
            "prod-nobucket-nopolicy",
            "prod-bucket-policy",
        ],
    )
    @pytest.mark.skipif(condition=not is_aws_cloud(), reason="not supported yet")
    @markers.aws.validated
    def test_nested_conditions(
        self,
        aws_client,
        deploy_cfn_template,
        cleanups,
        env_type,
        should_create_bucket,
        should_create_policy,
        snapshot,
    ):
        """
        Tests the case where a condition references another condition

        EnvType == "prod" && BucketName != "" ==> creates bucket + policy
        EnvType == "test" && BucketName != "" ==> creates bucket only
        EnvType == "test" && BucketName == "" ==> no resource created
        EnvType == "prod" && BucketName == "" ==> no resource created
        """
        bucket_name = f"ls-test-bucket-{short_uid()}" if should_create_bucket else ""
        stack_name = f"condition-test-stack-{short_uid()}"
        changeset_name = "initial"
        cleanups.append(lambda: aws_client.cloudformation.delete_stack(StackName=stack_name))
        snapshot.add_transformer(snapshot.transform.cloudformation_api())
        if bucket_name:
            snapshot.add_transformer(snapshot.transform.regex(bucket_name, "<bucket-name>"))
        snapshot.add_transformer(snapshot.transform.regex(stack_name, "<stack-name>"))

        template = load_file(
            os.path.join(THIS_DIR, "../../templates/conditions/nested-conditions.yaml")
        )
        create_cs_result = aws_client.cloudformation.create_change_set(
            StackName=stack_name,
            ChangeSetName=changeset_name,
            TemplateBody=template,
            ChangeSetType="CREATE",
            Parameters=[
                {"ParameterKey": "EnvType", "ParameterValue": env_type},
                {"ParameterKey": "BucketName", "ParameterValue": bucket_name},
            ],
        )
        snapshot.match("create_cs_result", create_cs_result)

        aws_client.cloudformation.get_waiter("change_set_create_complete").wait(
            ChangeSetName=changeset_name, StackName=stack_name
        )

        describe_changeset_result = aws_client.cloudformation.describe_change_set(
            ChangeSetName=changeset_name, StackName=stack_name
        )
        snapshot.match("describe_changeset_result", describe_changeset_result)
        aws_client.cloudformation.execute_change_set(
            ChangeSetName=changeset_name, StackName=stack_name
        )
        aws_client.cloudformation.get_waiter("stack_create_complete").wait(StackName=stack_name)

        stack_resources = aws_client.cloudformation.describe_stack_resources(StackName=stack_name)
        if should_create_policy:
            stack_policy = [
                sr
                for sr in stack_resources["StackResources"]
                if sr["ResourceType"] == "AWS::S3::BucketPolicy"
            ][0]
            snapshot.add_transformer(
                snapshot.transform.regex(stack_policy["PhysicalResourceId"], "<stack-policy>"),
                priority=-1,
            )

        snapshot.match("stack_resources", stack_resources)
        stack_events = aws_client.cloudformation.describe_stack_events(StackName=stack_name)
        snapshot.match("stack_events", stack_events)
        describe_stack_result = aws_client.cloudformation.describe_stacks(StackName=stack_name)
        snapshot.match("describe_stack_result", describe_stack_result)

        # manual assertions

        # check that bucket exists
        try:
            aws_client.s3.head_bucket(Bucket=bucket_name)
            bucket_exists = True
        except Exception:
            bucket_exists = False

        assert bucket_exists == should_create_bucket

        if bucket_exists:
            # check if a policy exists on the bucket
            try:
                aws_client.s3.get_bucket_policy(Bucket=bucket_name)
                bucket_policy_exists = True
            except Exception:
                bucket_policy_exists = False

            assert bucket_policy_exists == should_create_policy

    @pytest.mark.skipif(condition=not is_aws_cloud(), reason="not supported yet")
    @markers.aws.validated
    def test_output_reference_to_skipped_resource(self, deploy_cfn_template, aws_client, snapshot):
        """test what happens to outputs that reference a resource that isn't deployed due to a falsy condition"""
        with pytest.raises(aws_client.cloudformation.exceptions.ClientError) as e:
            deploy_cfn_template(
                template_path=os.path.join(
                    THIS_DIR, "../../templates/conditions/ref-condition-output.yaml"
                ),
                parameters={
                    "OptionParameter": "option-b",
                },
            )
        snapshot.match("unresolved_resource_reference_exception", e.value.response)

    # def test_updating_only_conditions_during_stack_update(self):
    #     ...

    # def test_condition_with_unsupported_intrinsic_functions(self):
    # ...

    @pytest.mark.parametrize(
        ["should_use_fallback", "match_value"],
        [
            (None, "FallbackParamValue"),
            ("true", "FallbackParamValue"),
            ("false", "DefaultParamValue"),
        ],
    )
    @markers.aws.validated
    def test_dependency_in_non_evaluated_if_branch(
        self, deploy_cfn_template, aws_client, should_use_fallback, match_value
    ):
        parameters = (
            {"ShouldUseFallbackParameter": should_use_fallback} if should_use_fallback else {}
        )
        stack = deploy_cfn_template(
            template_path=os.path.join(
                os.path.dirname(__file__),
                "../../templates/engine/cfn_if_conditional_reference.yaml",
            ),
            parameters=parameters,
        )
        param = aws_client.ssm.get_parameter(Name=stack.outputs["ParameterName"])
        assert param["Parameter"]["Value"] == match_value

    @markers.aws.validated
    def test_sub_in_conditions(self, deploy_cfn_template, aws_client):
        region = aws_client.cloudformation.meta.region_name
        topic_prefix = f"test-topic-{short_uid()}"
        suffix = short_uid()
        stack = deploy_cfn_template(
            template_path=os.path.join(
                os.path.dirname(__file__),
                "../../templates/conditions/intrinsic-functions-in-conditions.yaml",
            ),
            parameters={
                "TopicName": f"{topic_prefix}-{region}",
                "TopicPrefix": topic_prefix,
                "TopicNameWithSuffix": f"{topic_prefix}-{region}-{suffix}",
                "TopicNameSuffix": suffix,
            },
        )

        topic_arn = stack.outputs["TopicRef"]
        aws_client.sns.get_topic_attributes(TopicArn=topic_arn)
        assert topic_arn.split(":")[-1] == f"{topic_prefix}-{region}"

        topic_arn_with_suffix = stack.outputs["TopicWithSuffixRef"]
        aws_client.sns.get_topic_attributes(TopicArn=topic_arn_with_suffix)
        assert topic_arn_with_suffix.split(":")[-1] == f"{topic_prefix}-{region}-{suffix}"

    @markers.aws.validated
    @pytest.mark.parametrize("env,region", [("dev", "us-west-2"), ("production", "us-east-1")])
    def test_conditional_in_conditional(self, env, region, deploy_cfn_template, aws_client):
        stack = deploy_cfn_template(
            template_path=os.path.join(
                os.path.dirname(__file__),
                "../../templates/conditions/conditional-in-conditional.yml",
            ),
            parameters={
                "SelectedRegion": region,
                "Environment": env,
            },
        )

        if env == "production" and region == "us-east-1":
            assert stack.outputs["Result"] == "true"
        else:
            assert stack.outputs["Result"] == "false"
