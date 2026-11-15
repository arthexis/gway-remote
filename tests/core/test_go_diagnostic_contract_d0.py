"""Hermetic adversarial tests of the D0 contract; no I/O or subprocess."""
import unittest
from dataclasses import replace

from gway_remote.go_diagnostic_contract import (
    BarrierEvidence, ContractError, DiagnosticPlan, DiagnosticReceipt,
    Phase, SandboxPolicy, StepResult, assess_offline, transition,
)

SIM_SHA = "67e2d0e0fef704d7c693a6bd86af29bcc60db9a5"
REMOTE_SHA = "2de97a6fb889f8e809bc369910f9a62696c832a8"
STEPS = ("mod_tidy", "mod_verify", "build_backend", "build_uidlab")


def plan(**changes):
    return replace(DiagnosticPlan(
        request_id="diagnostic-01", simulator_sha=SIM_SHA,
        remote_sha=REMOTE_SHA, workspace="/tmp/go-diag-diagnostic-01",
    ), **changes)


def evidence(**changes):
    return replace(BarrierEvidence(
        schedule_covered=True, broker_covered=True, manual_covered=True,
        deployment_covered=True, owner_alive=True, no_competing_jobs=True,
        shared_lock_held=True, boot_verified=True,
    ), **changes)


def receipt(outcomes=("passed",) * 4, phase=Phase.SUCCEEDED,
            reason="ok", workspace_removed=True, processes_reaped=True):
    steps = tuple(StepResult(name, outcome, 0 if outcome == "passed"
                             else 2 if outcome == "failed" else None)
                  for name, outcome in zip(STEPS, outcomes))
    return DiagnosticReceipt(
        "diagnostic-01", SIM_SHA, phase, reason,
        steps, workspace_removed, processes_reaped,
    )


class TestOfflineGoContract(unittest.TestCase):
    def rejects(self, callback):
        with self.assertRaises(ContractError):
            callback()

    def test_valid_plan_is_only_declarative(self):
        self.assertEqual(assess_offline(plan(), evidence()),
                         "offline_contract_complete_not_runtime_authorization")

    def test_wrong_sha_or_target_fail_closed(self):
        for fields in (
            {"simulator_sha": "HEAD"}, {"remote_sha": "0" * 39},
            {"node": "gway-002"}, {"user": "root"}, {"arch": "amd64"},
            {"request_id": "../unsafe"}, {"request_id": ""},
        ):
            with self.subTest(fields=fields):
                self.rejects(lambda: plan(**fields).validate())

    def test_workspace_escape_and_aliases(self):
        for workspace in (
            "/home/arthe/.local/share/ocpp-simulator", "/tmp/../tmp/go-diag-diagnostic-01",
            "/tmp//go-diag-diagnostic-01", "/tmp/go-diag-other",
            "tmp/go-diag-diagnostic-01", "/tmp/go-diag-diagnostic-01/child",
            "/var/tmp/go-diag-diagnostic-01",
        ):
            with self.subTest(workspace=workspace):
                self.rejects(lambda: plan(workspace=workspace).validate())

    def test_resource_scope_cannot_expand_or_shrink(self):
        self.rejects(lambda: plan(resources=frozenset({"node:gway-001:compute"})).validate())
        self.rejects(lambda: plan(resources=frozenset({"node:gway-001:compute", "node:gway-001:ocpp-simulator", "node:watchtower"})).validate())

    def test_sandbox_security_flags(self):
        for flag in (
            "network_namespace", "readonly_host_mounts", "deny_host_sockets",
            "deny_credentials", "private_tmp", "no_new_privileges",
            "kill_process_group", "cleanup_required",
        ):
            with self.subTest(flag=flag):
                self.rejects(lambda: replace(SandboxPolicy(), **{flag: False}).validate())

    def test_resource_limits_and_bool_types(self):
        for field, value in (
            ("memory_mib", 128), ("memory_mib", 8192),
            ("memory_mib", True), ("max_go_parallelism", 0),
            ("max_go_parallelism", 3), ("timeout_seconds", 59),
            ("timeout_seconds", 1201),
        ):
            with self.subTest(field=field, value=value):
                self.rejects(lambda: replace(SandboxPolicy(), **{field: value}).validate())

    def test_all_entrypoints_need_same_barrier(self):
        for field in (
            "schedule_covered", "broker_covered", "manual_covered",
            "deployment_covered", "owner_alive", "no_competing_jobs",
            "shared_lock_held", "boot_verified",
        ):
            with self.subTest(field=field):
                self.rejects(lambda: assess_offline(plan(), evidence(**{field: False})))

    def test_invalid_phase_jumps_and_terminal_replay(self):
        for current, dest in (
            (Phase.PLANNED, Phase.RUNNING), (Phase.RUNNING, Phase.SUCCEEDED),
            (Phase.SUCCEEDED, Phase.ADMITTED), (Phase.UNCERTAIN, Phase.RUNNING),
            (Phase.FAILED, Phase.FAILED),
        ):
            self.rejects(lambda: transition(current, dest))
        self.assertIs(transition(Phase.RUNNING, Phase.CLEANING), Phase.CLEANING)

    def test_success_requires_all_steps_and_cleanup(self):
        self.assertEqual(receipt().sanitized()["phase"], "succeeded")
        self.rejects(lambda: receipt(workspace_removed=False).sanitized())
        self.rejects(lambda: receipt(processes_reaped=False).sanitized())

    def test_failure_stops_before_later_builds(self):
        outcomes = ("passed", "failed", "not_run", "not_run")
        self.assertEqual(receipt(outcomes, Phase.FAILED, "step_failed").sanitized()["reason"],
                         "step_failed")
        self.rejects(lambda: receipt(("failed", "passed", "not_run", "not_run"),
                                     Phase.FAILED, "step_failed").sanitized())

    def test_sanitized_output_has_fixed_fields(self):
        data = receipt(("failed", "not_run", "not_run", "not_run"),
                       Phase.FAILED, "step_failed").sanitized()
        self.assertEqual(set(data), {
            "schema", "request_id", "simulator_sha", "phase", "reason",
            "steps", "workspace_removed", "processes_reaped",
        })
        self.assertNotIn("stderr", str(data))
        self.assertNotIn("stdout", str(data))

    def test_uncertain_cleanup_cannot_be_reported_as_failed(self):
        self.assertEqual(receipt(("failed", "not_run", "not_run", "not_run"),
                                 Phase.UNCERTAIN, "cleanup_unverified",
                                 workspace_removed=False).sanitized()["phase"], "uncertain")
        self.rejects(lambda: receipt(("failed", "not_run", "not_run", "not_run"),
                                     Phase.FAILED, "step_failed",
                                     workspace_removed=False).sanitized())

    def test_no_arbitrary_reason_or_step_names(self):
        self.rejects(lambda: receipt(reason="token=secret").sanitized())
        bad = replace(receipt(), steps=(StepResult("shell_command", "passed", 0),)
                      + receipt().steps[1:])
        self.rejects(bad.validate)

    def test_exit_code_and_outcome_consistent(self):
        bad = replace(receipt(), steps=(StepResult("mod_tidy", "passed", 2),)
                      + receipt().steps[1:])
        self.rejects(bad.validate)

    def test_out_of_order_step_rejected(self):
        original = receipt()
        self.rejects(lambda: replace(original, steps=original.steps[::-1]).validate())


if __name__ == "__main__":
    unittest.main()
