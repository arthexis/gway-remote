"""Run unittest groups with per-test timings; no third-party dependencies."""
import argparse
import sys
import time
import unittest
from pathlib import Path

GROUPS = ("codex", "core", "deployment", "infrastructure", "mobile", "simulator")
ROOT = Path(__file__).resolve().parents[2]


class TimedResult(unittest.TextTestResult):
    def startTest(self, test):
        self._started_at = time.perf_counter()
        super().startTest(test)

    def stopTest(self, test):
        elapsed = time.perf_counter() - self._started_at
        self.stream.writeln(f"TIMING {elapsed:.3f}s {test.id()}")
        super().stopTest(test)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", choices=(*GROUPS, "all"), default="all")
    args = parser.parse_args(argv)
    loader = unittest.TestLoader()
    start = ROOT / "tests" / args.group if args.group != "all" else ROOT / "tests"
    suite = loader.discover(str(start), pattern="test_*.py", top_level_dir=str(ROOT))
    started = time.perf_counter()
    result = unittest.TextTestRunner(verbosity=2, resultclass=TimedResult).run(suite)
    print(f"SUMMARY group={args.group} tests={result.testsRun} "
          f"failures={len(result.failures)} errors={len(result.errors)} "
          f"skipped={len(result.skipped)} duration={time.perf_counter()-started:.3f}s",
          flush=True)
    return 0 if result.wasSuccessful() and result.testsRun else 1


if __name__ == "__main__":
    sys.exit(main())
