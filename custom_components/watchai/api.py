"""Synchronous camera protocol, always called in an executor by Home Assistant.

Derived from Web 5.0 login/index JavaScript and a hardware-tested local script.
No camera credentials, sessions or tokens are logged. Commands are never retried.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

_LOGGER = logging.getLogger(__name__)
MAX_RESPONSE = 1024 * 1024


class CameraError(Exception):
    """A camera request failed."""


class CannotConnect(CameraError):
    """The camera cannot be reached."""


class InvalidAuth(CameraError):
    """Authentication was rejected."""


class UnsupportedProtocol(CameraError):
    """The response does not match the supported protocol."""


def normalize_host(value: str) -> str:
    """Accept a camera address with an optional scheme and port."""
    value = value.strip()
    if "://" not in value:
        value = "http://" + value
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid camera address") from exc
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment
            or any(c.isspace() for c in value)):
        raise ValueError("Enter only the camera hostname or IP and optional port")
    hostname = parsed.hostname.lower()
    if ":" in hostname:
        hostname = "[" + hostname + "]"
    default_port = 80 if parsed.scheme == "http" else 443
    suffix = f":{port}" if port is not None and port != default_port else ""
    return f"{parsed.scheme}://{hostname}{suffix}"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Do not forward authenticated camera requests to another URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Camera:
    """One short-lived login session; instances are not shared across threads."""

    def __init__(self, host: str, username: str, password: str):
        self.base = normalize_host(host)
        self.username = username
        self.password = password
        self.token = ""
        self.session = ""
        self.http = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect()
        )

    def command(self, number: int, elements: list[tuple[str, dict]]) -> ET.Element:
        attrs = {"Command": str(number)}
        if self.session:
            attrs["SessionId"] = self.session
        root = ET.Element("CommandHead", attrs)
        params = ET.SubElement(root, "Parameters", {"Version": "1"})
        for name, values in elements:
            ET.SubElement(params, name, {key: str(value) for key, value in values.items()})
        body = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json, text/plain, */*",
            "Origin": self.base,
            "Referer": self.base + "/index.html",
        }
        if self.token:
            headers["token"] = self.token
        request = urllib.request.Request(
            self.base + "/action/WEB_JsonAjax", data=body, headers=headers, method="POST"
        )
        try:
            with self.http.open(request, timeout=8) as response:
                self.token = response.headers.get("token") or self.token
                raw = response.read(MAX_RESPONSE + 1)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise InvalidAuth(f"Camera rejected authentication (HTTP {exc.code}).") from None
            raise CannotConnect(f"Camera returned HTTP {exc.code}.") from None
        except (urllib.error.URLError, OSError, TimeoutError):
            raise CannotConnect("Camera did not respond. Check its address and network connection.") from None
        if len(raw) > MAX_RESPONSE or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
            raise UnsupportedProtocol("Unexpected camera response format.")
        try:
            parsed = ET.fromstring(raw.strip())
        except ET.ParseError:
            raise UnsupportedProtocol("Camera did not return a valid XML response.") from None
        result = parsed.find("./Parameters/Result")
        code = result.get("Code") if result is not None else None
        if code in ("-507", "-508", "-512", "-515", "-669"):
            raise InvalidAuth(f"Camera rejected authentication (code {code}). No retry was sent.")
        if code != "0":
            raise CameraError(f"Command {number} failed (camera code {code}).")
        params = parsed.find("Parameters")
        if params is None:
            raise UnsupportedProtocol("Camera omitted response parameters.")
        return params

    def authenticate(self, operator: int = 2) -> None:
        params = self.command(11027, [("DigestAuthentication", {"OperatorType": 1})])
        challenge = params.find("DigestAuthentication")
        if challenge is None:
            raise UnsupportedProtocol("Camera omitted its authentication challenge.")
        algorithm = challenge.get("Algorithm", "").lower().replace("-", "")
        hash_name = {"md5": "md5", "sha256": "sha256", "sha1": "sha1"}.get(algorithm)
        if hash_name is None:
            raise UnsupportedProtocol("Camera uses an unsupported authentication algorithm.")

        def digest(value: str) -> str:
            return hashlib.new(hash_name, value.encode("utf-8")).hexdigest()

        realm, nonce, qop = (challenge.get(key) for key in ("Realm", "Nonce", "Qop"))
        if realm is None or not nonce or not qop:
            raise UnsupportedProtocol("Incomplete authentication challenge.")
        cnonce = base64.b64encode(secrets.token_hex(8).encode("ascii")).decode("ascii")
        nc, uri = "0000001", "active/base/onvif"
        ha1 = digest(f"{self.username}:{realm}:{self.password}")
        ha2 = digest(f"POST:{uri}")
        answer = digest(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}")
        params = self.command(11027, [("DigestAuthentication", {
            "OperatorType": operator, "User": self.username, "Realm": realm,
            "Cnonce": cnonce, "Qop": qop, "Nonce": nonce, "Uri": uri,
            "Nc": nc, "Response": answer,
        })])
        if operator == 2:
            auth = params.find("DigestAuthentication")
            session = auth.get("SessionId") if auth is not None else None
            if not session:
                raise UnsupportedProtocol("Camera omitted the login session ID.")
            self.session = session
        else:
            self.session = ""

    def execute(self, enabled: bool | None = None, duration: int = 5) -> None:
        """Log in, optionally control the lights, then log out. None only tests login."""
        if not isinstance(duration, int) or not 1 <= duration <= 1800:
            raise ValueError("Duration must be an integer between 1 and 1800 seconds.")
        try:
            self.authenticate()
            if enabled is not None:
                self.command(43917, [
                    ("ChannelId", {"Id": 1}),
                    ("RedBlueLedManualCtrState", {
                        "Enable": str(enabled).lower(), "Duration": duration,
                    }),
                ])
        finally:
            if self.session:
                try:
                    self.authenticate(operator=3)
                except CameraError:
                    # A failed cleanup must not make an accepted light command appear to fail.
                    _LOGGER.warning("Camera logout could not be confirmed; the session may remain until expiry")
                finally:
                    self.token = ""
                    self.session = ""
