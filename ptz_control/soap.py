"""Small SOAP 1.2 transport for the implemented ONVIF operations.

No external WSDL downloads, proxies, redirects or automatic movement retries.
One instance belongs to exactly one camera worker thread.
"""
import base64
import hashlib
import http.client
import re
import secrets
import ssl
import socket
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

from .errors import (AuthenticationError, ConfigurationError, ProtocolError,
                     SoapFault, TransportError)
from .models import CameraConfig

SOAP = "http://www.w3.org/2003/05/soap-envelope"
TT = "http://www.onvif.org/ver10/schema"
DEVICE = "http://www.onvif.org/ver10/device/wsdl"
MEDIA1 = "http://www.onvif.org/ver10/media/wsdl"
MEDIA2 = "http://www.onvif.org/ver20/media/wsdl"
PTZ = "http://www.onvif.org/ver20/ptz/wsdl"
WSSE = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
WSU = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"
TOKEN = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0"
BINARY = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0"
MAX_RESPONSE = 2 * 1024 * 1024
for prefix, uri in [("s", SOAP), ("tt", TT), ("tds", DEVICE), ("trt", MEDIA1),
                    ("tr2", MEDIA2), ("tptz", PTZ), ("wsse", WSSE), ("wsu", WSU)]:
    ET.register_namespace(prefix, uri)


def element(ns: str, name: str, text=None, **attributes) -> ET.Element:
    e = ET.Element(f"{{{ns}}}{name}", {k: str(v) for k, v in attributes.items()})
    if text is not None:
        e.text = str(text)
    return e


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def child(e: ET.Element, name: str) -> ET.Element | None:
    return next((v for v in e if local(v.tag) == name), None)


def children(e: ET.Element, name: str) -> list[ET.Element]:
    return [v for v in e if local(v.tag) == name]


def text(e: ET.Element, *path: str, default=None):
    for name in path:
        e = child(e, name)
        if e is None:
            return default
    return e.text if e.text is not None else default


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise TransportError("HTTP redirects are not permitted")


class _DeadlineHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    def http_open(self, req):
        owner = self.owner
        class Connection(http.client.HTTPConnection):
            def connect(self):
                super().connect()
                owner._watch_socket(self.sock)
        return self.do_open(Connection, req)


class _DeadlineHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, owner, context):
        super().__init__(context=context)
        self.owner = owner

    def https_open(self, req):
        owner = self.owner
        class Connection(http.client.HTTPSConnection):
            def connect(self):
                super().connect()
                owner._watch_socket(self.sock)
        return self.do_open(Connection, req, context=self._context,
                            check_hostname=self._check_hostname)


class SoapTransport:
    def __init__(self, config: CameraConfig):
        self.config = config
        self.clock_offset = 0.0
        self.validate_endpoint(config.device_url)
        self._openers = {}
        self._deadline = 0.0
        self._watchdogs = []

    def _watch_socket(self, connection_socket):
        """Shutdown a connected socket even if headers/body arrive as a trickle.

        DNS resolution / OS connect cannot be killed by a Python thread; the
        remaining budget is checked immediately after connection establishment.
        """
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            connection_socket.close()
            raise TransportError("SOAP connection exceeded response deadline")
        done = threading.Event()
        def expire():
            if done.is_set():
                return
            try:
                connection_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        watchdog = threading.Timer(remaining, expire)
        watchdog.daemon = True
        self._watchdogs.append((watchdog, done))
        watchdog.start()

    def validate_endpoint(self, url: str) -> str:
        try:
            u = urlsplit(url)
            root = urlsplit(self.config.device_url)
            if (u.scheme not in {"http", "https"} or not u.hostname or
                    u.username is not None or u.password is not None or u.fragment):
                raise ValueError()
            _ = u.port  # validate malformed ports
            allowed = {root.hostname, *self.config.allowed_service_hosts}
            if u.hostname not in allowed:
                raise ValueError()
            if root.scheme == "https" and u.scheme != "https":
                raise ValueError()
        except ValueError:
            raise ConfigurationError("invalid or unapproved service endpoint") from None
        return url

    def envelope(self, ns, operation, fields, authenticated=True):
        root = element(SOAP, "Envelope")
        if authenticated:
            header = ET.SubElement(root, f"{{{SOAP}}}Header")
            security = ET.SubElement(header, f"{{{WSSE}}}Security",
                                     {f"{{{SOAP}}}mustUnderstand": "true"})
            token = ET.SubElement(security, f"{{{WSSE}}}UsernameToken")
            nonce = secrets.token_bytes(16)
            created = (datetime.now(timezone.utc) + timedelta(seconds=self.clock_offset))
            created = created.isoformat(timespec="milliseconds").replace("+00:00", "Z")
            credentials = self.config.credentials
            digest = hashlib.sha1(nonce + created.encode() + credentials.password.encode()).digest()
            token.extend([
                element(WSSE, "Username", credentials.username),
                element(WSSE, "Password", base64.b64encode(digest).decode(),
                        Type=TOKEN + "#PasswordDigest"),
                element(WSSE, "Nonce", base64.b64encode(nonce).decode(),
                        EncodingType=BINARY + "#Base64Binary"),
                element(WSU, "Created", created),
            ])
        body = ET.SubElement(root, f"{{{SOAP}}}Body")
        request = ET.SubElement(body, f"{{{ns}}}{operation}")
        request.extend(fields)
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    def _opener(self, url, authenticated):
        key = (url, authenticated)
        if key not in self._openers:
            context = ssl.create_default_context(cafile=self.config.ca_file)
            handlers = [urllib.request.ProxyHandler({}), NoRedirect(),
                        _DeadlineHTTPHandler(self), _DeadlineHTTPSHandler(self, context)]
            if authenticated:
                passwords = urllib.request.HTTPPasswordMgrWithDefaultRealm()
                passwords.add_password(None, url, self.config.credentials.username,
                                       self.config.credentials.password)
                handlers.append(urllib.request.HTTPDigestAuthHandler(passwords))
            self._openers[key] = urllib.request.build_opener(*handlers)
        return self._openers[key]

    def call(self, url, ns, operation, fields=(), *, authenticated=True):
        self.validate_endpoint(url)
        payload = self.envelope(ns, operation, fields, authenticated)
        request = urllib.request.Request(url, data=payload, method="POST", headers={
            "Content-Type": f'application/soap+xml; charset=utf-8; action="{ns}/{operation}"',
            "Accept": "application/soap+xml",
            "Connection": "close",
        })
        started = time.monotonic()
        self._deadline = started + self.config.response_deadline
        try:
            try:
                response = self._opener(url, authenticated).open(
                    request, timeout=self.config.socket_timeout)
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    exc.close()
                    raise AuthenticationError("ONVIF authentication or authorization failed") from None
                response = exc  # SOAP faults often arrive with HTTP 400/500
            with response:
                status = response.status
                data = bytearray()
                while True:
                    if time.monotonic() - started > self.config.response_deadline:
                        raise TransportError("SOAP response deadline exceeded")
                    chunk = response.read1(min(65536, MAX_RESPONSE + 1 - len(data)))
                    if not chunk:
                        break
                    data.extend(chunk)
                    if len(data) > MAX_RESPONSE:
                        raise ProtocolError("SOAP response exceeds size limit")
            if time.monotonic() - started > self.config.response_deadline:
                raise TransportError("SOAP response deadline exceeded")
        except (urllib.error.URLError, OSError, TimeoutError, ValueError, http.client.HTTPException):
            raise TransportError("SOAP transport failed") from None
        finally:
            for watchdog, done in self._watchdogs:
                done.set()
                watchdog.cancel()
            self._watchdogs.clear()
        result = self.parse(bytes(data), ns, operation)
        if status != 200:
            raise TransportError("unexpected HTTP status")
        return result

    @staticmethod
    def parse(data: bytes, ns: str, operation: str):
        # UTF-8 only prevents alternate-encoding bypasses of DTD rejection.
        try:
            decoded = data.decode("utf-8-sig")
            if re.search(r"<!\s*(DOCTYPE|ENTITY)", decoded, re.IGNORECASE):
                raise ProtocolError("DTD and entity declarations are not permitted")
            root = ET.fromstring(decoded)
        except (UnicodeError, ET.ParseError):
            raise ProtocolError("invalid SOAP XML") from None
        if root.tag != f"{{{SOAP}}}Envelope":
            raise ProtocolError("expected SOAP 1.2 Envelope")
        body = root.find(f"{{{SOAP}}}Body")
        if body is None:
            raise ProtocolError("missing SOAP Body")
        fault = body.find(f"{{{SOAP}}}Fault")
        if fault is not None:
            codes = tuple(v.text or "" for v in fault.iter(f"{{{SOAP}}}Value"))
            if any(c.rsplit(":", 1)[-1] in {"NotAuthorized", "FailedAuthentication"} for c in codes):
                raise AuthenticationError("ONVIF authentication or authorization failed")
            raise SoapFault(codes)
        result = body.find(f"{{{ns}}}{operation}Response")
        if result is None:
            raise ProtocolError("unexpected SOAP response operation")
        return result

    def close(self):
        self._openers.clear()
