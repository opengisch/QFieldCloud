#!/bin/env python3
import argparse
import re
from pathlib import Path

import yaml


def get_env_varnames_from_envfile(filename: str) -> set[str]:
    result = set()

    with open(filename) as f:
        for line in f.readlines():
            if line.startswith(" "):
                continue

            if line.strip().startswith("#"):
                continue

            if len(line.strip()) == 0:
                continue

            variable_name = line.strip().split("=")[0]

            # not settings
            if variable_name in ["COMPOSE_FILE", "COMPOSE_PATH_SEPARATOR"]:
                continue

            result.add(variable_name)

        return result


def get_env_varnames_from_docker_compose(filename: Path) -> set[str]:
    regex = r"\$\{(\w+)(:-?\w+?)?\}"
    result = set()

    with open(filename) as f:
        for line in f.readlines():
            if line.strip().startswith("#"):
                continue

            for match in re.finditer(regex, line):
                result.add(match.group(1))

    return result


def get_env_varnames_from_docker_compose_files(
    search_path: str,
) -> dict[str, list[str]]:
    env_vars = {}

    for path in Path(search_path).glob("**/docker-compose*.yml"):
        assert path.is_file()

        for varname in get_env_varnames_from_docker_compose(path):
            occurrences = env_vars.get(varname, [])
            occurrences.append(path.name)
            env_vars[varname] = occurrences

    return env_vars


def get_env_varnames_from_k8s_kustomization(filename: Path) -> set[str]:
    result = set()

    with open(filename) as f:
        k8s_config = yaml.load(f, Loader=yaml.SafeLoader)
        for config in k8s_config["configMapGenerator"]:
            for envvar_and_val in config["literals"]:
                result.add(envvar_and_val.strip().split("=")[0])

    return result


def get_env_varnames_from_k8s_secrets(filename: Path) -> set[str]:
    with open(filename) as f:
        config = yaml.load(f, Loader=yaml.SafeLoader)
        return set(config["spec"]["encryptedData"].keys())


def get_env_varnames_from_k8s_environments(search_path: str) -> dict[str, list[str]]:
    env_vars = {}

    for path in Path(search_path).iterdir():
        if not path.is_dir():
            continue

        kustomization_varnames = get_env_varnames_from_k8s_kustomization(
            path.joinpath("kustomization.yml")
        )
        secret_varnames = get_env_varnames_from_k8s_secrets(path.joinpath("secret.yml"))

        common_varnames = kustomization_varnames.intersection(secret_varnames)
        assert len(common_varnames) == 0, (
            f"Envvar(s) {common_varnames} are present both in the kustomization and the secret file in {path.name} environment. Choose only one!"
        )

        for varname in kustomization_varnames.union(secret_varnames):
            occurrences = env_vars.get(varname, [])
            occurrences.append(path.name)
            env_vars[varname] = occurrences

    return env_vars


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="check_envvars",
        epilog="./check_envvars.py .env.example --docker-compose-dir . --k8s-environments-dir ./deployment/kubernetes/environments",
    )
    parser.add_argument("envfile", type=str, help="Environment file.")
    parser.add_argument(
        "--docker-compose-dir",
        type=str,
        help="Directory containing docker-compose*.yml files.",
    )
    parser.add_argument(
        "--k8s-environments-dir",
        type=str,
        help="Directory containing k8s configuration and secret files.",
    )
    parser.add_argument(
        "--ignored-varnames",
        type=str,
        nargs="*",
        help="Ignored varnames.",
    )
    args = parser.parse_args()

    problems = []
    envfile_vars = get_env_varnames_from_envfile(args.envfile)
    ignored_varnames = args.ignored_varnames or []

    if args.docker_compose_dir:
        dockercompose_vars = get_env_varnames_from_docker_compose_files(
            args.docker_compose_dir
        )

        for varname in envfile_vars.difference(set(dockercompose_vars.keys())):
            if varname in ignored_varnames:
                continue

            if varname in envfile_vars:
                problems.append(
                    f'Envvar "{varname}" is defined in the .env file, but not found in any docker-compose file.'
                )

            if varname in dockercompose_vars:
                problems.append(
                    f'Envvar "{varname}" is used in the docker-compose file(s) {dockercompose_vars[varname]}, but not defined in the .env file.'
                )

    if args.k8s_environments_dir:
        k8s_vars = get_env_varnames_from_k8s_environments(args.k8s_environments_dir)
        k8s_environments = [
            path.name for path in Path(args.k8s_environments_dir).iterdir()
        ]

        for varname in envfile_vars.difference(set(k8s_vars.keys())):
            if varname in ignored_varnames:
                continue

            if varname in envfile_vars:
                problems.append(
                    f'Envvar "{varname}" is defined in the .env file, but not found in the any k8s configuration(s) and secret(s).'
                )

            if varname in k8s_vars:
                problems.append(
                    f'Envvar "{varname}" is used in the k8s configuration(s) and secret(s) {k8s_vars[varname]}, but not defined in the .env file.'
                )

        for varname, occurrences in k8s_vars.items():
            if varname in ignored_varnames:
                continue

            for environment in occurrences:
                if environment not in k8s_environments:
                    problems.append(
                        f'Envvar "{varname}" should be in all k8s environments, but missing not found neither in configuration or secrets of "{environment}".'
                    )

    if len(problems) == 0:
        print("All envvars are ok.")
        exit(0)
    else:
        for problem in sorted(problems):
            print(problem)

        print(
            f"Some envvars are not passed properly, {len(problems)} problem(s) found."
        )
        exit(1)
