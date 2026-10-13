"""UI-4h source parity checks for simulator status/results panel presentation."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PALETTE = ROOT / "android/app/src/main/java/com/arthexis/gwayremote/OperationPalette.kt"
REGISTRY = ROOT / "android/app/src/main/java/com/arthexis/gwayremote/OperationRegistry.kt"


def test_simulator_results_are_presented_in_dedicated_panel():
    text = PALETTE.read_text()
    for marker in (
        'panel.id == "simulator-results"',
        'panel.id == "simulator-status"',
        "SimulatorActivitySummary.parse(log, truncated)",
        'result.optString("outcome", "unknown")',
        'result.optBoolean("truncated", false)',
        '"Show raw output"',
        '"Hide raw output"',
    ):
        assert marker in text


def test_read_only_operations_stay_safe_and_refreshable():
    registry = REGISTRY.read_text()
    for command in ("simulator-status", "simulator-results"):
        start = registry.index('OperationSpec("' + command + '"')
        assert 'ExecutionPolicy.AUTO_READ' in registry[start:start + 220]
    assert 'onRefresh(panel.id)' in PALETTE.read_text()
