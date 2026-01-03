import inspect
import io
import json
import sys
import tempfile
import traceback
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any, Callable

from qfieldcloud_sdk import sdk

from qfc_worker.exceptions import (
    InvalidXmlFileException,
    WorkflowModificationException,
    WorkflowValidationException,
)


class Workflow:
    def __init__(
        self,
        id: str,
        version: str,
        name: str,
        steps: list["Step"],
        description: str = "",
    ):
        self.id = id
        self.version = version
        self.name = name
        self.description = description
        self.steps = steps
        self._step_idx_by_id = self._get_step_idx_by_id(steps)

        self.validate()

    def validate(self):
        if not self.steps:
            raise WorkflowValidationException(
                f'The workflow "{self.id}" should contain at least one step.'
            )

        step_ids = set()
        all_step_returns = {}
        for step in self.steps:
            # check step id uniqueness
            if step.id in step_ids:
                raise WorkflowValidationException(
                    f'The workflow "{self.id}" has duplicated step id "{step.id}".'
                )

            step_ids.add(step.id)

            # check step parameters match the step method signature (no extra, no missing, no positional-only parameters)
            param_names = []
            sig = inspect.signature(step.method)
            for param in sig.parameters.values():
                if (
                    param.kind != inspect.Parameter.KEYWORD_ONLY
                    and param.kind != inspect.Parameter.POSITIONAL_OR_KEYWORD
                ):
                    raise WorkflowValidationException(
                        f'The workflow "{self.id}" method "{step.method.__name__}" has a non keyword parameter "{param.name}".'
                    )

                if param.default == inspect._empty and param.name not in step.arguments:
                    raise WorkflowValidationException(
                        f'The workflow "{self.id}" method "{step.method.__name__}" has an argument "{param.name}" without default value that is not available in the step definition "arguments", expected one of {list(step.arguments.keys())}.'
                    )

                param_names.append(param.name)

            # check step arguments match available previous step return values
            for name, value in step.arguments.items():
                if isinstance(value, StepOutput):
                    if value.step_id not in all_step_returns:
                        raise WorkflowValidationException(
                            f'The workflow "{self.id}" has step "{step.id}" that requires a non-existing step return value "{value.step_id}.{value.return_name}" for argument "{name}". Previous step with that id does not exist.'
                        )

                    if value.return_name not in all_step_returns[value.step_id]:
                        raise WorkflowValidationException(
                            f'The workflow "{self.id}" has step "{step.id}" that requires a non-existing step return value "{value.step_id}.{value.return_name}" for argument "{name}". Previous step with that id found, but returns no value with such name.'
                        )

                if name not in param_names:
                    raise WorkflowValidationException(
                        f'The workflow "{self.id}" method "{step.method.__name__}" receives a parameter "{name}" that is not available in the method definition, expected one of {param_names}.'
                    )

            all_step_returns[step.id] = all_step_returns.get(step.id, step.return_names)

    def _get_step_idx_by_id(self, steps: list["Step"]) -> dict[str, int]:
        step_idx_by_id = {}

        for idx, step in enumerate(steps):
            step_idx_by_id[step.id] = idx

        return step_idx_by_id

    def insert_step(
        self,
        step: "Step",
        before_id: str | None = None,
        after_id: str | None = None,
    ) -> None:
        if (before_id is None and after_id is None) or (
            before_id is not None and after_id is not None
        ):
            raise WorkflowModificationException(
                "Either before_id or after_id must be provided, but not both."
            )

        insert_idx = -1

        if before_id is not None:
            if before_id not in self._step_idx_by_id:
                raise WorkflowModificationException(
                    f'Step with id "{before_id}" not found.'
                )

            insert_idx = self._step_idx_by_id[before_id]

        if after_id is not None:
            if after_id not in self._step_idx_by_id:
                raise WorkflowModificationException(
                    f'Step with id "{after_id}" not found.'
                )

            insert_idx = self._step_idx_by_id[after_id] + 1

        if insert_idx == -1:
            raise WorkflowModificationException("Invalid insert index computed.")

        self.steps.insert(insert_idx, step)
        self._step_idx_by_id = self._get_step_idx_by_id(self.steps)


class Step:
    def __init__(
        self,
        id: str,
        name: str,
        method: Callable,
        arguments: dict[str, Any] | None = None,
        return_names: list[str] | None = None,
        outputs: list[str] | None = None,
    ) -> None:
        self.id = id
        self.name = name
        self.method = method
        self.arguments = arguments or {}
        # names of method return values
        self.return_names = return_names or []
        # names of method return values that will be part of the outputs. They are assumed to be safe to be shown to the user.
        self.outputs = outputs or []
        # stage of the step execution: 0 = not started, 1 = in progress, 2 = completed
        self.stage = 0


class StepOutput:
    def __init__(self, step_id: str, return_name: str) -> None:
        self.step_id = step_id
        self.return_name = return_name


class WorkDirPathBase:
    def __init__(self, *parts: str, mkdir: bool = False) -> None:
        self.parts = parts
        self.mkdir = mkdir

    def eval(self, root: Path) -> Path | str:
        path = root.joinpath(*self.parts)

        if self.mkdir:
            path.mkdir(parents=True, exist_ok=True)

        return path


class WorkDirPath(WorkDirPathBase):
    def eval(self, root: Path) -> Path:
        return Path(super().eval(root))


class WorkDirPathAsStr(WorkDirPathBase):
    def eval(self, root: Path) -> str:
        return str(super().eval(root))


@contextmanager
def logger_context(step: Step):
    log_uuid = uuid.uuid4()

    try:
        # NOTE we are still using the reference from the `steps` list
        step.stage = 1
        print(f"::<<<::{log_uuid} {step.name}", file=sys.stderr)
        yield
        step.stage = 2
    finally:
        print(f"::>>>::{log_uuid} {step.stage}", file=sys.stderr)


def json_default(obj):
    obj_str = type(obj).__qualname__

    try:
        obj_str += f" {str(obj)}"
    except Exception:
        obj_str += " <non-representable>"

    return f"<non-serializable: {obj_str}>"


def run_workflow(
    workflow: Workflow,
    feedback_filename: Path | IO | None,
) -> dict[str, Any]:
    """Executes the steps required to run a task and return structured feedback from the execution

    Each step has a method that is executed.
    Method may take arguments as defined in `arguments` and ordered in `arg_names`.
    Method may return values, as defined in `return_values`.
    Some return values can used as task output, as defined in `output_names`.
    Some return values can used as arguments for next steps, as defined in `public_returns`.

    Args:
        workflow: workflow to be executed
        feedback_filename: write feedback to an IO device, to Path filename, or don't write it
    """
    feedback: dict[str, Any] = {
        "feedback_version": "2.0",
        "workflow_version": workflow.version,
        "workflow_id": workflow.id,
        "workflow_name": workflow.name,
    }
    # it may be modified after the successful completion of each step.
    step_returns = {}

    try:
        root_workdir = Path(tempfile.mkdtemp())
        for step in workflow.steps:
            with logger_context(step):
                arguments = {
                    **step.arguments,
                }
                for name, value in arguments.items():
                    if isinstance(value, StepOutput):
                        arguments[name] = step_returns[value.step_id][value.return_name]
                    elif isinstance(value, WorkDirPathBase):
                        arguments[name] = value.eval(root_workdir)

                return_values = step.method(**arguments)

                # ensure the return values are always a tuple
                if len(step.return_names) <= 1:
                    return_values = (return_values,)

                step_returns[step.id] = {}
                for name, value in zip(step.return_names, return_values):
                    step_returns[step.id][name] = value

    except Exception as err:
        feedback["error"] = str(err)

        if isinstance(err, sdk.QfcRequestException):
            status_code = err.response.status_code

            if status_code == 401:
                feedback["error_type"] = "API_TOKEN_EXPIRED"
            elif status_code == 402:
                feedback["error_type"] = "API_PAYMENT_REQUIRED"
            elif status_code == 403:
                feedback["error_type"] = "API_FORBIDDEN"
            elif status_code == 404:
                feedback["error_type"] = "API_NOT_FOUND"
            elif status_code == 500:
                feedback["error_type"] = "API_INTERNAL_SERVER_ERROR"
            else:
                feedback["error_type"] = "API_OTHER"
        elif isinstance(err, FileNotFoundError):
            feedback["error_type"] = "FILE_NOT_FOUND"
        elif isinstance(err, InvalidXmlFileException):
            feedback["error_type"] = "INVALID_PROJECT_FILE"
        else:
            feedback["error_type"] = "UNKNOWN"

        _type, _value, tb = sys.exc_info()
        feedback["error_class"] = type(err).__name__
        feedback["error_stack"] = traceback.format_tb(tb)
    finally:
        feedback["steps"] = []
        feedback["outputs"] = {}

        for step in workflow.steps:
            step_feedback = {
                "id": step.id,
                "name": step.name,
                "stage": step.stage,
                "returns": {},
            }

            if step.stage == 2:
                step_feedback["returns"] = step_returns[step.id]
                feedback["outputs"][step.id] = {}
                for output_name in step.outputs:
                    feedback["outputs"][step.id][output_name] = step_returns[step.id][
                        output_name
                    ]

            feedback["steps"].append(step_feedback)

        if isinstance(feedback_filename, io.IOBase):
            feedback_filename.write("Feedback:")
            json.dump(
                feedback,
                feedback_filename,
                indent=2,
                sort_keys=True,
                default=json_default,
            )
        elif isinstance(feedback_filename, Path):
            with open(feedback_filename, "w") as f:
                json.dump(feedback, f, indent=2, sort_keys=True, default=json_default)

        return feedback
