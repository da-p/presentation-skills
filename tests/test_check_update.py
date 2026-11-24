import importlib.util
from io import BytesIO
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import URLError


script = Path(__file__).resolve().parents[1] / "skills/presentation-craft/scripts/check_update.py"
spec = importlib.util.spec_from_file_location("check_update", script)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class UpdateTests(unittest.TestCase):
    def test_only_newer_versions_trigger_an_offer(self):
        with patch.object(Path, "read_bytes", return_value=b"1.9.0\n"):
            for version, status in [
                ("1.10.0", "update_available"),
                ("1.9.0", "no_update"),
                ("1.8.9", "no_update"),
            ]:
                with self.subTest(version=version), patch.object(
                    checker, "urlopen", return_value=BytesIO(f"{version}\n".encode())
                ) as request:
                    self.assertEqual(checker.check_update(), {
                        "status": status, "installed": "1.9.0", "latest": version
                    })
                    request.assert_called_once_with(checker.VERSION_URL, timeout=3)

    def test_invalid_or_unavailable_remote_version(self):
        with patch.object(Path, "read_bytes", return_value=b"1.9.0\n"):
            for data in (b"<html>404</html>", b" " * 59 + b"2.0.0" + b"invalid"):
                with self.subTest(data=data), patch.object(
                    checker, "urlopen", return_value=BytesIO(data)
                ):
                    self.assertEqual(checker.check_update(), {
                        "status": "unavailable", "installed": "1.9.0"
                    })
            with patch.object(checker, "urlopen", side_effect=URLError("offline")):
                self.assertEqual(checker.check_update(), {
                    "status": "unavailable", "installed": "1.9.0"
                })

    def test_missing_local_version_skips_network_request(self):
        with patch.object(Path, "read_bytes", side_effect=FileNotFoundError), patch.object(
            checker, "urlopen"
        ) as request:
            self.assertEqual(checker.check_update(), {"status": "unavailable"})
            request.assert_not_called()
