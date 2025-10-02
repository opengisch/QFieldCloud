#!/usr/bin/env python3

import argparse
import logging
from pathlib import Path
from typing import Any

from qfc_worker.workflow import Workflow, run_workflow

logger = logging.getLogger(__name__)


parser = argparse.ArgumentParser(prog="COMMAND")
subparsers = parser.add_subparsers(dest="cmd")


class QfcBaseCommandRegistry(type):
    registry = {}

    def __new__(mcs, name, bases, attrs):
        cls = super().__new__(mcs, name, bases, attrs)

        if name == "QfcBaseCommand":
            return cls

        module_path = attrs.get("__module__")

        if module_path:
            command_name = module_path.split(".")[-1]

            if command_name in mcs.registry:
                raise Exception(
                    f"Only one command definition allowed per file. Check the definition of {cls.__name__}."
                )

            setattr(cls, "command_name", command_name)

            mcs.registry[command_name] = cls

        return cls


class QfcBaseCommand(metaclass=QfcBaseCommandRegistry):
    command_name: str
    """Command name, derived from the module (file) name and used to call the command from CLI"""

    command_help: str = ""
    """Help text for the command, shown in CLI help"""

    def __init__(self) -> None:
        self.parser = self.create_parser()

    def create_parser(self) -> argparse.ArgumentParser:
        parser = subparsers.add_parser(self.command_name, help=self.command_help)
        parser.set_defaults(func=self.handle)

        self.add_arguments(parser)

        return parser

    def run_from_argv(self) -> None:
        options = self.parser.parse_args()

        cmd_options = vars(options)
        # Move positional args out of options to mimic legacy optparse
        args = cmd_options.pop("args", ())

        self.handle(*args, **cmd_options)

    def handle(self, *args: Any, **options: Any) -> None:
        """
        The actual logic of the command. Subclasses could reimplement this method,
        but always provide feedback.json path as output.
        """
        workflow = self.get_workflow(*args, **options)

        run_workflow(
            workflow,
            Path("/io/feedback.json"),
        )

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """
        Entry point for subclassed commands to add custom arguments.
        """
        pass

    def get_workflow(self, /, **kwargs) -> Workflow:
        """
        The actual logic of the command. Subclasses must implement
        this method.
        """
        raise NotImplementedError(
            "subclasses of QfcBaseCommand must provide a `get_workflow()` method"
        )


def run_command() -> None:
    # import all commands so they register themselves
    import qfc_worker.commands  # noqa: F401

    args: argparse.Namespace = parser.parse_args()

    options = vars(args)

    if hasattr(args, "func") is False:
        parser.print_help()
        return

    # temporarily store the function to call, as if removed from options, it would not be available in the args method anymore
    command_func = args.func

    # remove the keys that would not be expected by the `handle` method
    options.pop("cmd")
    options.pop("func")

    command_func(**options)
