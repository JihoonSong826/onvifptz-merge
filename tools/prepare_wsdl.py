"""Explicit build-time download of official WSDL/XSD dependencies.

Run: python tools/prepare_wsdl.py --output wsdl_bundle
Camera credentials are never used. Runtime schema loading is local-only.
Keep original notices in downloaded files; do not relabel schemas as MIT.
"""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import build_opener, ProxyHandler, HTTPRedirectHandler
import xml.etree.ElementTree as ET

ROOTS = {
    "http://www.onvif.org/ver10/device/wsdl": "https://www.onvif.org/ver10/device/wsdl/devicemgmt.wsdl",
    "http://www.onvif.org/ver10/media/wsdl": "https://www.onvif.org/ver10/media/wsdl/media.wsdl",
    "http://www.onvif.org/ver20/media/wsdl": "https://www.onvif.org/ver20/media/wsdl/media.wsdl",
    "http://www.onvif.org/ver20/ptz/wsdl": "https://www.onvif.org/ver20/ptz/wsdl/ptz.wsdl",
}
HOSTS = {"www.onvif.org", "www.w3.org", "docs.oasis-open.org"}


def fetch_url(url):
    u = urlsplit(url)
    if u.scheme not in {"http", "https"} or u.hostname not in HOSTS or u.username or u.password or u.port:
        raise ValueError("schema URL is outside the official source allowlist")
    return urlunsplit(("https", u.netloc, u.path, u.query, ""))


class OfficialRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req, fp, code, msg, headers, fetch_url(newurl))


def prepare(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    opener = build_opener(ProxyHandler({}), OfficialRedirect())
    documents = {}
    queue = list(ROOTS.values())
    while queue:
        logical_url = queue.pop(0)
        if logical_url in documents:
            continue
        if len(documents) >= 64:
            raise ValueError("too many schema dependencies")
        with opener.open(fetch_url(logical_url), timeout=20) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError("schema exceeds size limit")
        decoded = raw.decode("utf-8-sig")
        if "<!DOCTYPE" in decoded.upper() or "<!ENTITY" in decoded.upper():
            raise ValueError("DTD/entity declaration in schema")
        tree = ET.fromstring(decoded)
        filename = hashlib.sha256(logical_url.encode()).hexdigest() + ".xml"
        (directory / filename).write_bytes(raw)
        documents[logical_url] = {"file": filename, "sha256": hashlib.sha256(raw).hexdigest()}
        for item in tree.iter():
            if item.tag in {"{http://www.w3.org/2001/XMLSchema}import",
                            "{http://www.w3.org/2001/XMLSchema}include",
                            "{http://www.w3.org/2001/XMLSchema}redefine",
                            "{http://schemas.xmlsoap.org/wsdl/}import"}:
                location = item.get("schemaLocation") or item.get("location")
                if location:
                    dependency = urljoin(logical_url, location)
                    fetch_url(dependency)
                    queue.append(dependency)
    (directory / "manifest.json").write_text(json.dumps(
        {"roots": ROOTS, "documents": documents}, indent=2), encoding="utf-8")
    print(f"Prepared {len(documents)} local schema documents in {directory}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="wsdl_bundle")
    prepare(parser.parse_args().output)
