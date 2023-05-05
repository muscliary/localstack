import copy
from typing import Final

from jsonpath_ng import parse

from localstack.services.stepfunctions.asl.component.eval_component import EvalComponent
from localstack.services.stepfunctions.asl.eval.environment import Environment


class ResultPath(EvalComponent):
    DEFAULT_PATH: Final[str] = "$"

    def __init__(self, result_path_src: str):
        self.result_path_src: Final[str] = result_path_src

    def _eval_body(self, env: Environment) -> None:
        result_expr = parse(self.result_path_src)
        result = copy.deepcopy(env.stack.pop())
        if env.inp is None:
            env.inp = dict()
        env.inp = result_expr.update_or_create(env.inp, result)
