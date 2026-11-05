"""Optional WSDL-backed request codec over the existing bounded HTTP transport.

Zeep never performs camera I/O or remote schema downloads here. Requests use
Zeep XSD types; responses retain the existing checked ElementTree API. This is
not full response-schema validation or an ONVIF conformance test.
"""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from .backend import OnvifBackend
from .errors import ConfigurationError, ProtocolError
from .soap import SoapTransport, SOAP


class WsdlBundle:
    """Integrity-checked local schema catalog. One immutable snapshot per worker."""
    def __init__(self, directory):
        self.root = Path(directory).resolve()
        try:
            manifest = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
            self.roots = dict(manifest["roots"])
            self.data = {}
            for uri, entry in manifest["documents"].items():
                path = (self.root / entry["file"]).resolve()
                if not path.is_relative_to(self.root):
                    raise ValueError()
                raw = path.read_bytes()
                if len(raw) > 8 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                    raise ValueError()
                self.data[uri] = raw
            if not self.roots or any(uri not in self.data for uri in self.roots.values()):
                raise ValueError()
        except (OSError, ValueError, KeyError, TypeError):
            raise ConfigurationError("invalid local WSDL bundle or integrity mismatch") from None

    def load(self, uri):
        # The preparation tool fetches HTTP imports over HTTPS. Zeep also
        # upgrades same-host imports; both identifiers refer to those bytes.
        if uri not in self.data and uri.startswith("https://"):
            uri = "http://" + uri[len("https://"):]
        try:
            return self.data[uri]
        except KeyError:
            raise ConfigurationError("WSDL import absent from local catalog; network loading is disabled") from None


class ZeepSoapTransport(SoapTransport):
    """Lazily load local WSDL on the camera worker and render typed requests."""
    def __init__(self, config, wsdl_directory):
        super().__init__(config)
        self.wsdl_directory = wsdl_directory
        self._bundle = None
        self._clients = {}

    def _client(self, ns):
        if ns in self._clients:
            return self._clients[ns]
        try:
            from zeep import Client, Settings
        except ImportError:
            raise ConfigurationError("install the zeep extra: pip install '.[zeep]'") from None
        if self._bundle is None:
            self._bundle = WsdlBundle(self.wsdl_directory)
        bundle = self._bundle

        class LocalTransport:
            def load(self, url):
                return bundle.load(url)

            def post_xml(self, *args, **kwargs):
                raise ConfigurationError("Zeep network transport is disabled")

        try:
            uri = bundle.roots[ns]
            client = Client(uri, transport=LocalTransport(), settings=Settings(
                strict=True, xml_huge_tree=False, forbid_dtd=True,
                # Zeep calls WSDL/XSD imports "external" too. Permit catalog
                # imports, while LocalTransport rejects every unlisted URI.
                forbid_entities=True, forbid_external=False))
        except ConfigurationError:
            raise
        except Exception:
            raise ConfigurationError("unable to load service WSDL from local bundle") from None
        self._clients[ns] = client
        return client

    def envelope(self, ns, operation, fields, authenticated=True):
        # The base transport continues to own nonce, clock offset, authentication,
        # redirects, TLS, size limits, and slow-header/body response deadlines.
        client = self._client(ns)
        try:
            from lxml import etree
            request = ET.Element(f"{{{ns}}}{operation}")
            request.extend(fields)
            parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
            source = etree.fromstring(ET.tostring(request, encoding="utf-8"), parser)
            schema_element = client.get_element(f"{{{ns}}}{operation}")
            value = schema_element.parse(source, client.wsdl.types)
            if value is None:
                value = schema_element()
            parent = etree.Element("container")
            schema_element.render(parent, value)
            typed_request = ET.fromstring(etree.tostring(parent[0], encoding="utf-8"))
        except Exception:
            raise ProtocolError("outgoing request does not match the configured WSDL") from None
        envelope = ET.fromstring(super().envelope(ns, operation, (), authenticated))
        body = envelope.find(f"{{{SOAP}}}Body")
        body.remove(body[0])
        body.append(typed_request)
        return ET.tostring(envelope, encoding="utf-8", xml_declaration=True)

    def close(self):
        self._clients.clear()
        self._bundle = None
        super().close()


def zeep_backend_factory(wsdl_directory):
    """Use with CameraManager(backend_factory=zeep_backend_factory(path))."""
    def factory(config):
        return OnvifBackend(config, ZeepSoapTransport(config, wsdl_directory))
    return factory
