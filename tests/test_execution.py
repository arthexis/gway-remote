import tempfile
import unittest
from pathlib import Path
from gway_remote.execution import appliance_lock

class TestExecutionLock(unittest.TestCase):
    def test_exclusive(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lock"
            with appliance_lock(path):
                with self.assertRaises(RuntimeError):
                    with appliance_lock(path):
                        pass

if __name__ == "__main__":
    unittest.main()
