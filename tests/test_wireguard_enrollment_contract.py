import base64
import json
import unittest

from gway_remote.wireguard_enrollment_contract import (
    InvalidEnrollment, parse_enrollment_json, validate_enrollment,
)


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.request = {
            "device": "gway-004",
            "public_key": base64.b64encode(bytes(range(32))).decode("ascii"),
            "token": "a" * 43,
        }

    def test_valid_request(self):
        self.assertEqual(validate_enrollment(self.request)[0], "gway-004")
        self.assertEqual(parse_enrollment_json(json.dumps(self.request).encode())[2], "a" * 43)

    def test_unknown_or_missing_fields(self):
        for change in ({"unexpected": "x"}, {"token": None}, {"device": "test"}):
            with self.subTest(change=change):
                with self.assertRaises(InvalidEnrollment):
                    validate_enrollment({**self.request, **change})
        with self.assertRaises(InvalidEnrollment):
            validate_enrollment({"device": "gway-004", "public_key": self.request["public_key"]})

    def test_public_key_length_and_encoding(self):
        for key in ("bad", base64.b64encode(b"x" * 31).decode(), "!" * 44):
            with self.subTest(key=key):
                with self.assertRaises(InvalidEnrollment):
                    validate_enrollment({**self.request, "public_key": key})

    def test_bounded_body_and_no_secret_in_errors(self):
        for raw in (b"", b"x" * 4097, b"not-json", json.dumps({**self.request, "token": "SECRET"}).encode()):
            with self.assertRaises(InvalidEnrollment) as error:
                parse_enrollment_json(raw)
            self.assertNotIn("SECRET", str(error.exception))

    def test_rejects_array(self):
        with self.assertRaises(InvalidEnrollment):
            parse_enrollment_json(b"[]")


if __name__ == "__main__":
    unittest.main()
