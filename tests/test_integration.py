import json
import unittest
from ptz_control import CameraManager, CameraConfig, Credentials
from ptz_control.backend import OnvifBackend
from ptz_control.errors import ConfigurationError
from ptz_control.integration import xml_data
from ptz_control.simulation import SimulatedTransport, simulated_backend
from ptz_control.soap import PTZ, element


class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_json_snapshot_and_queries_do_not_export_credentials(self):
        config = CameraConfig("c", "http://c.invalid/device", Credentials("private-user", "private-pass"))
        async with CameraManager(backend_factory=simulated_backend) as manager:
            camera = await manager.add(config)
            payload = json.dumps(camera.snapshot())
            self.assertNotIn("private-user", payload)
            self.assertNotIn("private-pass", payload)
            self.assertEqual(camera.snapshot()["state"], "ready")
            self.assertIn("GetNodesResponse", (await camera.get_nodes_data())["tag"])
            self.assertIn("GetConfigurationResponse", (await camera.get_configuration_data())["tag"])

    def test_explicit_service_override_is_used(self):
        cfg = CameraConfig("c", "http://c.invalid/device", Credentials("u", "p"),
                           service_urls=((PTZ, "http://c.invalid/explicit-ptz"),))
        backend = OnvifBackend(cfg, SimulatedTransport(cfg))
        backend.connect()
        self.assertEqual(backend.ptz_url, "http://c.invalid/explicit-ptz")

    def test_override_validation_and_freeze(self):
        pairs = [[PTZ, "http://c.invalid/ptz"]]
        cfg = CameraConfig("c", "http://c.invalid/device", Credentials("u", "p"), service_urls=pairs)
        pairs[0][1] = "changed"
        self.assertEqual(cfg.service_urls[0][1], "http://c.invalid/ptz")
        for bad in (((PTZ, "x"), (PTZ, "y")), (("unknown", "x"),), ("bad",)):
            with self.assertRaises(ConfigurationError):
                CameraConfig("c", "http://c.invalid/device", Credentials("u", "p"), service_urls=bad)

    def test_override_does_not_bypass_endpoint_allowlist(self):
        cfg = CameraConfig("c", "http://c.invalid/device", Credentials("u", "p"),
                           service_urls=((PTZ, "http://other.invalid/ptz"),))
        transport = SimulatedTransport(cfg)
        with self.assertRaises(ConfigurationError):
            OnvifBackend(cfg, transport).connect()
        self.assertEqual(transport.calls, [])

    def test_xml_data_preserves_namespaces_and_repeated_children(self):
        root = element(PTZ, "Root", key="value")
        root.extend([element(PTZ, "Item", "one"), element(PTZ, "Item", "two")])
        data = xml_data(root)
        self.assertEqual(data["tag"], "{" + PTZ + "}Root")
        self.assertEqual([x["text"] for x in data["children"]], ["one", "two"])
        json.dumps(data)
