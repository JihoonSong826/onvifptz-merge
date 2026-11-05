"""Explicit JSON-ready data for host adapters; never serialize credentials."""
from dataclasses import asdict
import xml.etree.ElementTree as ET


def xml_data(node: ET.Element) -> dict:
    """Lossless namespace-aware element tree shape, not a vendor-specific schema."""
    return {"tag": node.tag, "attributes": dict(node.attrib), "text": node.text,
            "children": [xml_data(item) for item in node]}


def controller_snapshot(camera) -> dict:
    """Local lifecycle/capability snapshot, NOT a live health probe or motor state."""
    return {"camera_id": camera.config.camera_id,
            "state": camera.state, "last_error": camera.last_error,
            "capabilities": asdict(camera.capabilities) if camera.capabilities else None}
