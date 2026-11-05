import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET

from ptz_control.errors import ConfigurationError, ProtocolError, TransportError
from ptz_control.zeep_transport import WsdlBundle, ZeepSoapTransport
from ptz_control.soap import PTZ, SOAP, element
from tests import test_soap as http_tests

HAS_ZEEP = importlib.util.find_spec("zeep") is not None
# Original minimal fixture, not copied from ONVIF. Tests local codec mechanics.
FIXTURE = f'''<definitions xmlns="http://schemas.xmlsoap.org/wsdl/"
 xmlns:xsd="http://www.w3.org/2001/XMLSchema" targetNamespace="{PTZ}">
 <types><xsd:schema targetNamespace="{PTZ}" elementFormDefault="qualified">
 <xsd:element name="Stop"><xsd:complexType><xsd:sequence>
 <xsd:element name="ProfileToken" type="xsd:string"/>
 <xsd:element name="PanTilt" type="xsd:boolean" minOccurs="0"/>
 <xsd:element name="Zoom" type="xsd:boolean" minOccurs="0"/>
 </xsd:sequence></xsd:complexType></xsd:element>
 </xsd:schema></types></definitions>'''


def bundle_at(path, content=FIXTURE):
    raw = content.encode()
    (path / "fixture.xml").write_bytes(raw)
    uri = "https://schemas.invalid/fixture.wsdl"
    manifest = {"roots": {PTZ: uri}, "documents": {uri: {
        "file": "fixture.xml", "sha256": hashlib.sha256(raw).hexdigest()}}}
    (path / "manifest.json").write_text(json.dumps(manifest))


class BundleTests(unittest.TestCase):
    def test_hash_and_missing_import_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            bundle_at(path)
            catalog = WsdlBundle(path)
            with self.assertRaises(ConfigurationError):
                catalog.load("https://unlisted.invalid/schema")
            (path / "fixture.xml").write_text("modified")
            with self.assertRaises(ConfigurationError):
                WsdlBundle(path)

    def test_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            bundle_at(path)
            manifest = json.loads((path / "manifest.json").read_text())
            next(iter(manifest["documents"].values()))["file"] = "../outside.xml"
            (path / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaises(ConfigurationError):
                WsdlBundle(path)


@unittest.skipUnless(HAS_ZEEP, "install .[zeep] for the optional codec tests")
class CodecTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        bundle_at(self.path)
        self.transport = ZeepSoapTransport(http_tests.configuration(), self.path)

    def test_typed_request_preserves_token_and_optional_axis_omission(self):
        raw = self.transport.envelope(PTZ, "Stop", [element(PTZ, "ProfileToken", "p<&>")])
        request = ET.fromstring(raw).find(f"{{{SOAP}}}Body")[0]
        self.assertEqual(len(request), 1)
        self.assertEqual(request[0].text, "p<&>")

    def test_missing_and_unexpected_fields_are_rejected(self):
        for fields in ([], [element(PTZ, "WrongToken", "p")]):
            with self.assertRaises(ProtocolError):
                self.transport.envelope(PTZ, "Stop", fields)

    def test_unlisted_remote_import_does_not_fetch(self):
        bundle_at(self.path, FIXTURE.replace('<xsd:element name="Stop">',
            '<xsd:import namespace="urn:outside" schemaLocation="https://unlisted.invalid/a.xsd"/>'
            '<xsd:element name="Stop">'))
        with self.assertRaises(ConfigurationError):
            self.transport.envelope(PTZ, "Stop", [element(PTZ, "ProfileToken", "p")])

    def test_dtd_is_rejected(self):
        bundle_at(self.path, '<!DOCTYPE definitions [<!ENTITY x "secret">]>' + FIXTURE)
        with self.assertRaises(ConfigurationError):
            self.transport.envelope(PTZ, "Stop", [element(PTZ, "ProfileToken", "p")])


@unittest.skipUnless(HAS_ZEEP, "install .[zeep] for optional HTTP tests")
class ZeepHttpTests(http_tests.HttpIntegrationTests):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        bundle_at(self.path)

    def call(self):
        return ZeepSoapTransport(http_tests.configuration(self.url), self.path).call(
            self.url, PTZ, "Stop", [element(PTZ, "ProfileToken", "p1")])

    def test_total_deadline_covers_trickling_headers(self):
        type(self).mode = "slow_headers"
        transport = ZeepSoapTransport(http_tests.configuration(
            self.url, socket_timeout=.2, response_deadline=.1), self.path)
        # Load schemas before measuring connected I/O budget.
        transport._client(PTZ)
        started = time.monotonic()
        with self.assertRaises((TransportError, ProtocolError)):
            transport.call(self.url, PTZ, "Stop", [element(PTZ, "ProfileToken", "p1")])
        self.assertLess(time.monotonic() - started, .4)


@unittest.skipUnless(HAS_ZEEP and os.environ.get("ONVIF_TEST_WSDL_DIR"),
                     "requires optional Zeep and an explicitly prepared official WSDL bundle")
class OfficialSchemaTests(unittest.TestCase):
    def test_backend_requests_against_official_wsdl(self):
        from ptz_control import CameraConfig, Credentials
        from ptz_control.backend import OnvifBackend
        from ptz_control.simulation import SimulatedTransport
        for media2 in (False, True):
            cfg = CameraConfig("c", "http://c.invalid/device", Credentials("u", "p"),
                               allow_unbounded_moves=True, allow_persistent_writes=True)
            codec = ZeepSoapTransport(cfg, os.environ["ONVIF_TEST_WSDL_DIR"])
            class CheckedSimulation(SimulatedTransport):
                def call(self, url, ns, op, fields=(), **kw):
                    codec.envelope(ns, op, fields, kw.get("authenticated", True))
                    return super().call(url, ns, op, fields, **kw)
            backend = OnvifBackend(cfg, CheckedSimulation(cfg, media2=media2))
            backend.connect()
            backend.move(.1, -.2, .1, .3)
            backend.stop(); backend.status(); backend.presets()
            backend.absolute_move(.1, .2); backend.relative_move(zoom=.1)
            backend.set_preset("test"); backend.remove_preset("p")
            backend.goto_preset("p"); backend.goto_home(); backend.set_home()
            backend.get_nodes(); backend.get_configuration()
            codec.close()
