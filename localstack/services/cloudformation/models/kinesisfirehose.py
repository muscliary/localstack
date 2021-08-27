from localstack.services.cloudformation.service_models import GenericBaseModel
from localstack.utils.aws import aws_stack


class FirehoseDeliveryStream(GenericBaseModel):
    @staticmethod
    def cloudformation_type():
        return "AWS::KinesisFirehose::DeliveryStream"

    def fetch_state(self, stack_name, resources):
        stream_name = self.props.get("DeliveryStreamName") or self.resource_id
        stream_name = self.resolve_refs_recursively(stack_name, stream_name, resources)
        return aws_stack.connect_to_service("firehose").describe_delivery_stream(
            DeliveryStreamName=stream_name
        )
