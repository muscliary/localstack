import json
from typing import Final, Optional

from botocore.exceptions import ClientError

from localstack.aws.api.lambda_ import InvocationRequest, InvocationResponse, InvocationType
from localstack.aws.api.stepfunctions import HistoryEventType, TaskFailedEventDetails
from localstack.services.stepfunctions.asl.component.common.error_name.custom_error_name import (
    CustomErrorName,
)
from localstack.services.stepfunctions.asl.component.common.error_name.failure_event import (
    FailureEvent,
)
from localstack.services.stepfunctions.asl.component.state.state_execution.state_task.service.resource import (
    LambdaResource,
)
from localstack.services.stepfunctions.asl.component.state.state_execution.state_task.state_task import (
    StateTask,
)
from localstack.services.stepfunctions.asl.eval.environment import Environment
from localstack.services.stepfunctions.asl.eval.event.event_detail import EventDetails
from localstack.utils.aws.aws_stack import connect_to_service
from localstack.utils.strings import to_bytes, to_str


class LambdaFunctionErrorException(Exception):
    function_error: Final[Optional[str]]
    payload: Final[str]

    def __init__(self, function_error: Optional[str], payload: str):
        self.function_error = function_error
        self.payload = payload


class StateTaskLambda(StateTask):
    resource: LambdaResource

    @staticmethod
    def _error_cause_from_client_error(client_error: ClientError) -> tuple[str, str]:
        error_code: str = client_error.response["Error"]["Code"]
        error_msg: str = client_error.response["Error"]["Message"]
        response_details = "; ".join(
            [
                "Service: AWSLambda",
                f"Status Code: {client_error.response['ResponseMetadata']['HTTPStatusCode']}",
                f"Error Code: {error_code}",
                f"Request ID: {client_error.response['ResponseMetadata']['RequestId']}",
                "Proxy: null",
            ]
        )
        error = f"Lambda.{error_code}"
        cause = f"{error_msg} ({response_details})"
        return error, cause

    def _from_error(self, env: Environment, ex: Exception) -> FailureEvent:
        # TODO: produce snapshot tests to adjust the following errors.
        if isinstance(ex, LambdaFunctionErrorException):
            return FailureEvent(
                error_name=CustomErrorName("Exception"),
                event_type=HistoryEventType.TaskFailed,
                event_details=EventDetails(
                    taskFailedEventDetails=TaskFailedEventDetails(
                        error="Exception",
                        cause=ex.payload,
                    )
                ),
            )
        elif isinstance(ex, ClientError):
            error, cause = self._error_cause_from_client_error(ex)
            return FailureEvent(
                error_name=CustomErrorName(error),
                event_type=HistoryEventType.TaskFailed,
                event_details=EventDetails(
                    taskFailedEventDetails=TaskFailedEventDetails(
                        error=error,
                        cause=cause,
                    )
                ),
            )
        return super()._from_error(env=env, ex=ex)

    def _eval_execution(self, env: Environment) -> None:
        # TODO: check type? input (file) path as lm input? raw binary inputs? always json?
        tmp = env.stack.pop()

        parameters: InvocationRequest = dict()
        parameters["FunctionName"] = self.resource.resource_arn
        parameters["Payload"] = to_bytes(json.dumps(tmp))  # TODO: IO[bytes]
        parameters["InvocationType"] = InvocationType.RequestResponse
        if self.parameters:
            self.parameters.eval(env=env)
            gen_parameters: dict = env.stack.pop()

            parameters.update(gen_parameters)
            p_payload = parameters["Payload"]
            if not isinstance(p_payload, bytes):
                if not isinstance(p_payload, str):
                    p_payload = json.dumps(p_payload)
                parameters["Payload"] = to_bytes(p_payload)  # TODO: IO[bytes]

        # TODO: check for type and support other types.
        lambda_client = connect_to_service("lambda")
        invocation_resp: InvocationResponse = lambda_client.invoke(**parameters)

        func_error: Optional[str] = invocation_resp.get("FunctionError")
        if func_error:
            payload = json.loads(to_str(invocation_resp["Payload"].read()))
            payload_str = json.dumps(payload, separators=(",", ":"))
            raise LambdaFunctionErrorException(func_error, payload_str)

        # TODO: supported response types?
        resp_payload = invocation_resp["Payload"].read()
        resp_payload_str = to_str(resp_payload)
        resp_payload_json: json = json.loads(resp_payload_str)
        resp_payload_json.pop("ResponseMetadata", None)

        env.stack.append(resp_payload_json)
