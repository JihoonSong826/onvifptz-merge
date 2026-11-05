import unittest
from dataclasses import replace

from ptz_control.backend import OnvifBackend, duration
from ptz_control.errors import ConfigurationError, Unsupported, ProtocolError, SoapFault
from ptz_control.models import CameraConfig, Credentials
from ptz_control.simulation import SimulatedTransport
from ptz_control.soap import PTZ, TT, MEDIA2, child, element, text


def config(**kw):
    return CameraConfig("cam", "http://camera.invalid/device", Credentials("user", "secret"), **kw)


class BackendTests(unittest.TestCase):
    def make(self, cfg=None, **kw):
        cfg = cfg or config()
        wire = SimulatedTransport(cfg, **kw)
        backend = OnvifBackend(cfg, wire)
        backend.connect()
        return backend, wire

    def test_media1_tokens_and_move_wire(self):
        b, w = self.make()
        b.move(.2, -.3, .4, .1)
        op, fields, _ = w.calls[-1]
        self.assertEqual(op, "ContinuousMove")
        self.assertEqual(fields[0].tag, f"{{{PTZ}}}ProfileToken")
        self.assertEqual(fields[0].text, "profile-0")
        self.assertEqual(fields[1][0].tag, f"{{{TT}}}PanTilt")
        self.assertEqual(fields[1][0].get("x"), "0.2")
        self.assertEqual(fields[-1].text, "PT0.100000S")

    def test_media2_requests_all_configuration_types(self):
        b, w = self.make(media2=True)
        fields = next(fields for op, fields, _ in w.calls if op == "GetProfiles")
        self.assertEqual(fields[0].tag, f"{{{MEDIA2}}}Type")
        self.assertEqual(fields[0].text, "All")
        self.assertEqual(b.capabilities.binding.source_token, "sensor-0")

    def test_ambiguous_profiles_fail_closed(self):
        with self.assertRaises(ConfigurationError):
            self.make(multiple_profiles=True)
        b, _ = self.make(config(profile_token="profile-1"), multiple_profiles=True)
        self.assertEqual(b.capabilities.binding.profile_token, "profile-1")

    def test_source_selection(self):
        b, _ = self.make(config(video_source_token="sensor-1"), multiple_profiles=True)
        self.assertEqual(b.capabilities.binding.profile_token, "profile-1")

    def test_missing_profile_and_zoom(self):
        with self.assertRaises(Unsupported):
            self.make(config(profile_token="missing"))
        b, w = self.make(zoom=False)
        b.move(.1, 0, 0, .1)
        self.assertEqual(len(w.calls[-1][1][1]), 1)
        with self.assertRaises(Unsupported):
            b.move(0, 0, .1, .1)

    def test_nonfinite_and_out_of_range_rejected_without_io(self):
        b, w = self.make()
        count = len(w.calls)
        for value in (float("nan"), float("inf"), 1.01, -1.01):
            with self.assertRaises(ConfigurationError):
                b.move(value, 0, 0, .1)
        self.assertEqual(len(w.calls), count)

    def test_timeout_safety(self):
        b, w = self.make()
        for seconds in (0, -1, 2, float("nan")):
            with self.assertRaises(ConfigurationError):
                b.move(.1, 0, 0, seconds)
        b.capabilities = replace(b.capabilities, timeout_min=2)
        with self.assertRaises(ConfigurationError):
            b.move(.1, 0, 0, .1)
        b.capabilities = replace(b.capabilities, timeout_min=None, timeout_max=None)
        with self.assertRaises(Unsupported):
            b.move(.1, 0, 0, .1)

    def test_optional_movements_and_persistent_writes_gated(self):
        b, _ = self.make()
        for fn in (lambda: b.absolute_move(.1, 0), lambda: b.relative_move(.1, 0),
                   lambda: b.goto_preset("x"), b.goto_home,
                   lambda: b.set_preset("x"), b.set_home, lambda: b.remove_preset("x")):
            with self.assertRaises(Unsupported):
                fn()

    def test_optional_movements_use_correct_fields(self):
        b, w = self.make(config(allow_unbounded_moves=True, allow_persistent_writes=True))
        b.absolute_move(.5, -.5)
        self.assertEqual(w.calls[-1][1][1].tag, f"{{{PTZ}}}Position")
        b.relative_move(zoom=.1)
        self.assertEqual(w.calls[-1][1][1].tag, f"{{{PTZ}}}Translation")
        self.assertEqual(b.set_preset("test"), "preset-new")
        b.goto_preset("preset-new")
        b.goto_home()
        b.remove_preset("preset-new")
        b.set_home()

    def test_stop_omits_filters_for_all_axes(self):
        b, w = self.make()
        b.stop()
        self.assertEqual(len(w.calls[-1][1]), 1)

    def test_duration_parser(self):
        self.assertEqual(duration("PT0.5S"), .5)
        self.assertEqual(duration("P1DT2H3M4S"), 93784)
        for bad in ("P", "PT", "P1M", "bad", "-PT1S"):
            with self.assertRaises(ProtocolError):
                duration(bad)

    def test_capabilities_fallback_only_for_unsupported(self):
        class OldTransport(SimulatedTransport):
            def call(self, url, ns, op, fields=(), **kw):
                if op == "GetServices":
                    raise SoapFault(("ter:ActionNotSupported",))
                if op == "GetCapabilities":
                    response = element(ns, op + "Response")
                    caps = element(ns, "Capabilities")
                    for name in ("PTZ", "Media"):
                        item = element(TT, name)
                        item.append(element(TT, "XAddr", "http://camera.invalid/" + name))
                        caps.append(item)
                    response.append(caps)
                    return response
                return super().call(url, ns, op, fields, **kw)
        c = config()
        b = OnvifBackend(c, OldTransport(c))
        self.assertEqual(b.connect().binding.profile_token, "profile-0")
