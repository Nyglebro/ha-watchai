"""Protocol regressions using synthetic responses, never a real camera."""
import base64
import hashlib
import importlib.util
import io
from email.message import Message
from pathlib import Path
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

PATH = Path(__file__).parents[1] / "custom_components/watchai/api.py"
SPEC = importlib.util.spec_from_file_location("watchai_protocol", PATH)
api = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(api)


class Response(io.BytesIO):
    def __init__(self, body, token=None):
        super().__init__(body.encode())
        self.headers = Message()
        if token is not None:
            self.headers["token"] = token


def reply(extra="", code="0", token=None):
    return Response(
        f'<CommandHead><Parameters><Result Code="{code}"/>{extra}</Parameters></CommandHead>',
        token,
    )


class CameraSimulator:
    """Validate each request against an independent server-side digest calculation."""
    def __init__(self, testcase, algorithm="SHA-256", reject=None, fail_logout=False):
        self.test = testcase
        self.algorithm = algorithm
        self.reject = reject
        self.fail_logout = fail_logout
        self.requests = []
        self.token = None
        self.logged_in = False

    def open(self, request, timeout):
        root = ET.fromstring(request.data)
        self.requests.append(root)
        t = self.test
        t.assertEqual(request.get_header("Token"), self.token)
        t.assertEqual(request.full_url, "http://camera.test/action/WEB_JsonAjax")
        t.assertEqual(request.method, "POST")
        t.assertNotIn(b"secret-password", request.data)
        self.token = "token-" + str(len(self.requests))
        command = root.get("Command")
        params = root.find("Parameters")
        if command == "43917":
            t.assertTrue(self.logged_in)
            t.assertEqual(root.get("SessionId"), "test-session")
            if self.reject:
                return reply(code=self.reject, token=self.token)
            return reply(token=self.token)
        t.assertEqual(command, "11027")
        auth = params.find("DigestAuthentication")
        if auth.get("OperatorType") == "1":
            return reply(
                f'<DigestAuthentication Algorithm="{self.algorithm}" Realm="test-realm" '
                'Nonce="server-nonce" Qop="auth"/>', token=self.token,
            )
        t.assertEqual(auth.get("Nc"), "0000001")
        t.assertEqual(auth.get("Uri"), "active/base/onvif")
        t.assertEqual(auth.get("User"), 'a<&"dmin')
        t.assertEqual(len(base64.b64decode(auth.get("Cnonce"))), 16)
        hasher = hashlib.sha256 if self.algorithm == "SHA-256" else hashlib.md5
        digest = lambda value: hasher(value.encode()).hexdigest()
        expected = digest(":".join([
            digest('a<&"dmin:test-realm:secret-password'), "server-nonce", "0000001",
            auth.get("Cnonce"), "auth", digest("POST:active/base/onvif"),
        ]))
        t.assertEqual(auth.get("Response"), expected)
        if auth.get("OperatorType") == "2":
            self.logged_in = True
            return reply('<DigestAuthentication SessionId="test-session"/>', token=self.token)
        t.assertEqual(auth.get("OperatorType"), "3")
        self.logged_in = False
        return reply(code="-669" if self.fail_logout else "0", token=self.token)


class ProtocolTests(unittest.TestCase):
    def camera(self, **kwargs):
        camera = api.Camera("camera.test", 'a<&"dmin', "secret-password")
        camera.http = CameraSimulator(self, **kwargs)
        return camera

    def test_flash_session_tokens_digest_and_logout(self):
        for algorithm in ["SHA-256", "MD5"]:
            with self.subTest(algorithm=algorithm):
                camera = self.camera(algorithm=algorithm)
                camera.execute(True, 10)
                self.assertEqual(len(camera.http.requests), 5)
                lights = camera.http.requests[2].find("./Parameters/RedBlueLedManualCtrState")
                self.assertEqual(lights.attrib, {"Enable": "true", "Duration": "10"})
                self.assertEqual(camera.session, "")
                self.assertEqual(camera.token, "")

    def test_stop(self):
        camera = self.camera()
        camera.execute(False)
        lights = camera.http.requests[2].find("./Parameters/RedBlueLedManualCtrState")
        self.assertEqual(lights.get("Enable"), "false")

    def test_setup_validation_does_not_activate_lights(self):
        camera = self.camera()
        camera.execute()
        self.assertEqual(len(camera.http.requests), 4)
        self.assertTrue(all(r.get("Command") == "11027" for r in camera.http.requests))

    def test_light_rejection_is_not_retried_and_still_logs_out(self):
        camera = self.camera(reject="-669")
        with self.assertRaises(api.InvalidAuth):
            camera.execute(True)
        self.assertEqual(sum(r.get("Command") == "43917" for r in camera.http.requests), 1)
        self.assertFalse(camera.http.logged_in)

    def test_logout_failure_does_not_mask_accepted_flash(self):
        camera = self.camera(fail_logout=True)
        with self.assertLogs(api._LOGGER, level="WARNING"):
            camera.execute(True)
        self.assertEqual(camera.session, "")

    def test_unknown_algorithm_stops_before_sending_credentials(self):
        camera = self.camera(algorithm="UNKNOWN")
        with self.assertRaises(api.UnsupportedProtocol):
            camera.execute(True)
        self.assertEqual(len(camera.http.requests), 1)

    def test_rejected_login_is_not_retried(self):
        camera = self.camera()
        with patch.object(camera.http, "open", return_value=reply(code="-508")) as send:
            with self.assertRaises(api.InvalidAuth):
                camera.execute(True)
            self.assertEqual(send.call_count, 1)

    def test_invalid_xml_and_entity_declarations(self):
        for raw in ["<html>broken", '<!DOCTYPE x [<!ENTITY a "b">]><x/>']:
            camera = self.camera()
            with patch.object(camera.http, "open", return_value=Response(raw)):
                with self.assertRaises(api.UnsupportedProtocol):
                    camera.execute()

    def test_duration_validation_happens_before_network_io(self):
        for duration in [0, 1801, 1.5]:
            camera = self.camera()
            with self.assertRaises(ValueError):
                camera.execute(True, duration)
            self.assertEqual(camera.http.requests, [])

    def test_address_normalization(self):
        self.assertEqual(api.normalize_host(" camera.test/ "), "http://camera.test")
        self.assertEqual(api.normalize_host("http://CAMERA.test:80"), "http://camera.test")
        self.assertEqual(api.normalize_host("https://camera.test:8443"), "https://camera.test:8443")
        self.assertEqual(api.normalize_host("http://[::1]:8000"), "http://[::1]:8000")
        for value in ["", "http://camera.test/path", "ftp://camera.test", "http://u:p@camera.test", "http://camera.test?a=b"]:
            with self.assertRaises(ValueError):
                api.normalize_host(value)


if __name__ == "__main__":
    unittest.main()
