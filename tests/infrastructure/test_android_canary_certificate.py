import hashlib
from pathlib import Path
import struct
import tempfile
import unittest

from gway_remote.android_canary_certificate import certificate_sha256
from gway_remote.android_canary_install import InstallBlocked


def lp(value):
    return struct.pack("<I", len(value)) + value


def synthetic_apk(cert, multiple=False):
    signed = lp(b"") + lp(lp(cert))
    signer = lp(lp(signed))
    v2 = lp(signer + (signer if multiple else b""))
    entry = struct.pack("<Q", len(v2)+4) + struct.pack("<I", 0x7109871a) + v2
    size = len(entry)+24
    block = struct.pack("<Q", size) + entry + struct.pack("<Q", size) + b"APK Sig Block 42"
    end = struct.pack("<4s4H2IH", b"PK\x05\x06", 0, 0, 0, 0, 0, len(block), 0)
    return block+end


class CertificateTests(unittest.TestCase):
    def extract(self, content):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"app.apk"
            path.write_bytes(content)
            return certificate_sha256(path)

    def test_distinct_certificates(self):
        for cert in (b"cert one", b"cert two"):
            self.assertEqual(self.extract(synthetic_apk(cert)), hashlib.sha256(cert).hexdigest())

    def test_invalid_and_multiple_fail_closed(self):
        for invalid in (b"", synthetic_apk(b"cert", multiple=True), synthetic_apk(b"")):
            with self.assertRaises(InstallBlocked):
                self.extract(invalid)

    def test_audit_workflow_has_same_hardware_lock(self):
        workflow = (Path(__file__).resolve().parents[2]/".github/workflows/android-canary-certificate.yml").read_text()
        self.assertIn("group: gway-001-android-canary-install", workflow)
        self.assertIn("github.actor == 'arthexis'", workflow)
        self.assertIn("refs/heads/main", workflow)
        self.assertNotIn("secrets.", workflow)
        self.assertNotIn("uninstall", workflow)


    def test_stable_audit_reads_only_public_apk_and_version(self):
        from types import SimpleNamespace
        from gway_remote.android_canary_certificate import installed_evidence
        from gway_remote.android_canary_install import PRODUCTION
        payload = synthetic_apk(b"stable certificate")
        calls = []
        def call(argv, timeout):
            calls.append(argv)
            args = argv[1:]
            if args == ["devices", "-l"]:
                output = "List of devices attached\nLAB device usb:1-1 product:lab\n"
            elif args == ["-s", "LAB", "shell", "getprop", "ro.kernel.qemu"]:
                output = "0\n"
            elif args == ["-s", "LAB", "shell", "pm", "path", PRODUCTION]:
                output = "package:/data/app/com.arthexis.gwayremote-1/base.apk\n"
            elif args[:3] == ["-s", "LAB", "pull"]:
                self.assertEqual(args[3], "/data/app/com.arthexis.gwayremote-1/base.apk")
                Path(args[4]).write_bytes(payload)
                output = "1 file pulled"
            elif args == ["-s", "LAB", "shell", "dumpsys", "package", PRODUCTION]:
                output = "    versionCode=793 minSdk=26 targetSdk=35\n"
            else:
                self.fail("unexpected command")
            return SimpleNamespace(returncode=0, stdout=output)
        result = installed_evidence(PRODUCTION, call=call)
        self.assertEqual(result["package"], PRODUCTION)
        self.assertEqual(result["version_code"], 793)
        self.assertEqual(result["apk_sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(result["certificate_sha256"], hashlib.sha256(b"stable certificate").hexdigest())
        self.assertEqual(len(calls), 5)

    def test_arbitrary_package_denied_before_usb_access(self):
        from unittest.mock import Mock
        from gway_remote.android_canary_certificate import installed_evidence
        call = Mock()
        with self.assertRaisesRegex(InstallBlocked, "package_not_allowed"):
            installed_evidence("other.app", call=call)
        call.assert_not_called()
