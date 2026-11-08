"""Explicit CLI registration and dispatch composition.

Registration order is part of the public --help contract. Individual command
modules own their argparse definitions and execution; this module only wires them.
"""
import argparse

from . import deploy, local, operations, security


# Each registration group preserves the original positional ordering.
REGISTRATION = (
    (local, ("run",)),
    (security, ("bearer", "exec")),
    (deploy, ("deploy-targets", "reconcile")),
    (operations, ("diagnose",)),
    (local, ("watch",)),
    (operations, ("status", "hardware", "network")),
    (local, ("watchdog", "probe-csms")),
    (operations, ("logs",)),
    (local, ("report-bundle",)),
    (deploy, ("retention", "deployments", "deploy", "deploy-batch")),
    (security, ("host-key", "wireguard", "inspection-host-rotate",
                "inspection-host-pin", "register", "watchtower")),
    (local, ("codex", "api")),
)


def build_parser(tasks, targets):
    parser = argparse.ArgumentParser(description="Run an approved gway-001 workload")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for module, names in REGISTRATION:
        if module is local:
            module.register(subparsers, names, tasks)
        elif module is security:
            module.register(subparsers, names)
        else:
            module.register(subparsers, targets, names)
    return parser


def dispatch(args, parser, *, run_task, deployers):
    if local.dispatch(args, parser, run_task=run_task):
        return True
    if security.dispatch(args, parser):
        return True
    if operations.dispatch(args, parser):
        return True
    if deploy.dispatch(args, parser, deployers=deployers):
        return True
    return False
