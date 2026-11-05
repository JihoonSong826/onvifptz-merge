import base64
import hashlib
import io
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
import xml.etree.ElementTree as ET

from ptz_control import CameraConfig, Credentials
from ptz_control.errors import AuthenticationError, ConfigurationError, ProtocolError, SoapFault, TransportError
from ptz_control.soap import SOAP, PTZ, WSSE, WSU, SoapTransport, element, MAX_RESPONSE


def configuration(url="http://camera.invalid/device", **kw):
    return CameraConfig("cam", url, Credentials("operator", "secret<&>"), **kw)


def response(operation="Stop", content=""):
    return (f'<s:Envelope xmlns:s="{SOAP}"><s:Body>'
            f'<p:{operation}Response xmlns:p="{PTZ}">{content}</p:{operation}Response>'
            '</s:Body></s:Envelope>').encode()


class SoapTests(unittest.TestCase):
    def test_username_token_digest_and_unique_nonce(self):
        t = SoapTransport(configuration())
        first = ET.fromstring(t.envelope(PTZ, "Stop", [element(PTZ, "ProfileToken", "p<&>")]))
        token = first.find(f".//{{{WSSE}}}UsernameToken")
        nonce = token.findtext(f"{{{WSSE}}}Nonce")
        created = token.findtext(f"{{{WSU}}}Created")
        expected = base64.b64encode(hashlib.sha1(base64.b64decode(nonce) + created.encode()
                                                + b"secret<&>").digest()).decode()
        self.assertEqual(token.findtext(f"{{{WSSE}}}Password"), expected)
        second = ET.fromstring(t.envelope(PTZ, "Stop", []))
        self.assertNotEqual(nonce, second.findtext(f".//{{{WSSE}}}Nonce"))
        self.assertEqual(first.findtext(f".//{{{PTZ}}}ProfileToken"), "p<&>")
        self.assertNotIn("secret", repr(configuration()))

    def test_endpoint_validation(self):
        t = SoapTransport(configuration())
        for url in ("http://evil.invalid/ptz", "file:///tmp/wsdl", "http://u:p@camera.invalid/",
                    "http://camera.invalid:bad/", "http://camera.invalid/ptz#fragment"):
            with self.assertRaises(ConfigurationError):
                t.validate_endpoint(url)
        t = SoapTransport(configuration(allowed_service_hosts=("camera-alias.invalid",)))
        t.validate_endpoint("http://camera-alias.invalid:8080/ptz")
        with self.assertRaises(ConfigurationError):
            SoapTransport(configuration("https://camera.invalid/device")).validate_endpoint(
                "http://camera.invalid/ptz")

    def test_faults_and_sensitive_error_text(self):
        fault = (f'<s:Envelope xmlns:s="{SOAP}"><s:Body><s:Fault><s:Code>'
                 '<s:Value>s:Sender</s:Value><s:Subcode><s:Value>ter:NoProfile</s:Value>'
                 '</s:Subcode></s:Code><s:Reason><s:Text>secret-password</s:Text>'
                 '</s:Reason></s:Fault></s:Body></s:Envelope>').encode()
        with self.assertRaises(SoapFault) as caught:
            SoapTransport.parse(fault, PTZ, "Stop")
        self.assertTrue(caught.exception.has("NoProfile"))
        self.assertNotIn("secret-password", str(caught.exception))
        with self.assertRaises(AuthenticationError):
            SoapTransport.parse(fault.replace(b"NoProfile", b"NotAuthorized"), PTZ, "Stop")

    def test_bad_xml_and_wrong_response_rejected(self):
        for data in (b"not xml", b'<!DOCTYPE x [<!ENTITY a "x">]><x/>',
                     '<x/>'.encode("utf-16"), response("ContinuousMove")):
            with self.assertRaises(ProtocolError):
                SoapTransport.parse(data, PTZ, "Stop")


class HttpIntegrationTests(unittest.TestCase):
    """Actual urllib, HTTP and XML on localhost; no cameras or external network."""
    @classmethod
    def setUpClass(cls):
        cls.mode = "success"
        cls.requests = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                data = self.rfile.read(int(self.headers["Content-Length"]))
                cls.requests.append((self.headers, data))
                if cls.mode == "slow_headers":
                    try:
                        for byte in b"HTTP/1.1 200 OK\r\nX-Slow: header\r\n\r\n":
                            self.wfile.write(bytes([byte]))
                            self.wfile.flush()
                            threading.Event().wait(.02)
                    except (ConnectionError, OSError):
                        pass
                    return
                if cls.mode == "redirect":
                    self.send_response(302)
                    self.send_header("Location", "/redirect-target")
                    self.end_headers()
                    return
                if cls.mode == "denied":
                    self.send_response(401)
                    self.end_headers()
                    return
                if cls.mode == "digest" and not self.headers.get("Authorization"):
                    self.send_response(401)
                    self.send_header("WWW-Authenticate", 'Digest realm="camera", nonce="abc123", qop="auth", algorithm=MD5')
                    self.end_headers()
                    return
                if cls.mode == "digest":
                    # Verify the actual digest, not just the presence of a header.
                    import urllib.request
                    raw = self.headers["Authorization"].removeprefix("Digest ")
                    parts = urllib.request.parse_keqv_list(urllib.request.parse_http_list(raw))
                    md5 = lambda s: hashlib.md5(s.encode()).hexdigest()
                    ha1 = md5("operator:camera:secret<&>")
                    ha2 = md5("POST:" + parts["uri"])
                    expected = md5(f'{ha1}:abc123:{parts["nc"]}:{parts["cnonce"]}:auth:{ha2}')
                    if parts["response"] != expected:
                        self.send_response(403)
                        self.end_headers()
                        return
                body = b"x" * (MAX_RESPONSE + 1) if cls.mode == "oversize" else response()
                self.send_response(200)
                self.send_header("Content-Type", "application/soap+xml")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (ConnectionError, OSError):
                    pass
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/device"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(2)

    def setUp(self):
        type(self).mode = "success"
        type(self).requests = []

    def call(self):
        return SoapTransport(configuration(self.url)).call(
            self.url, PTZ, "Stop", [element(PTZ, "ProfileToken", "p1")])

    def test_actual_post_has_soap_action_and_body(self):
        self.call()
        headers, body = self.requests[0]
        self.assertIn(f'action="{PTZ}/Stop"', headers["Content-Type"])
        self.assertEqual(ET.fromstring(body).findtext(f".//{{{PTZ}}}ProfileToken"), "p1")

    def test_http_digest_challenge(self):
        type(self).mode = "digest"
        self.call()
        self.assertEqual(len(self.requests), 2)
        self.assertTrue(self.requests[1][0]["Authorization"].startswith("Digest "))

    def test_401_is_not_retried_forever(self):
        type(self).mode = "denied"
        with self.assertRaises(AuthenticationError):
            self.call()
        self.assertEqual(len(self.requests), 1)

    def test_redirect_does_not_leak_credentials(self):
        type(self).mode = "redirect"
        with self.assertRaises(TransportError):
            self.call()
        self.assertEqual(len(self.requests), 1)

    def test_response_size_limit(self):
        type(self).mode = "oversize"
        with self.assertRaises(ProtocolError):
            self.call()

    def test_total_deadline_covers_trickling_headers(self):
        type(self).mode = "slow_headers"
        transport = SoapTransport(configuration(self.url, socket_timeout=.2, response_deadline=.1))
        started = time.monotonic()
        with self.assertRaises((TransportError, ProtocolError)):
            transport.call(self.url, PTZ, "Stop", [element(PTZ, "ProfileToken", "p1")])
        self.assertLess(time.monotonic() - started, .4)
