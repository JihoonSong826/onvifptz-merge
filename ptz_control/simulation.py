"""Deterministic OFFLINE camera. Never connects to any network endpoint.

The real OnvifBackend consumes these SOAP responses so the demo also exercises
profile binding, ranges and real command construction. This is not conformance
certification and cannot prove a camera physically stops.
"""
import copy
import threading
import time
import xml.etree.ElementTree as ET

from .backend import OnvifBackend
from .errors import SoapFault, TransportError
from .soap import DEVICE, MEDIA1, MEDIA2, PTZ, TT, SoapTransport, element, text


class SimulatedTransport:
    def __init__(self, config, *, media2=False, multiple_profiles=False,
                 zoom=True, delay=0.0, fail_move=False, fail_stop=False):
        self.config = config
        self.clock_offset = 0
        self.media2 = media2
        self.multiple_profiles = multiple_profiles
        self.zoom = zoom
        self.delay = delay
        self.fail_move = fail_move
        self.fail_stop = fail_stop
        self.calls = []
        self.closed = False
        self.move_started = threading.Event()
        self.device_deadline = 0
        self.moving = False
        self.validator = SoapTransport(config)

    def validate_endpoint(self, url):
        return self.validator.validate_endpoint(url)

    def call(self, url, ns, operation, fields=(), *, authenticated=True):
        fields = list(fields)
        self.calls.append((operation, copy.deepcopy(fields), time.monotonic()))
        response = element(ns, operation + "Response")
        if operation == "GetSystemDateAndTime":
            response.append(element(TT, "SystemDateAndTime"))
        elif operation == "GetServices":
            for n, path in ((PTZ, "ptz"), (MEDIA2 if self.media2 else MEDIA1, "media")):
                service = element(DEVICE, "Service")
                service.extend([element(DEVICE, "Namespace", n), element(
                    DEVICE, "XAddr", self.config.device_url.rsplit("/", 1)[0] + "/" + path)])
                response.append(service)
        elif operation == "GetProfiles":
            for i in range(2 if self.multiple_profiles else 1):
                profile = element(ns, "Profiles", token=f"profile-{i}")
                cfg = element(TT, "PTZ" if self.media2 else "PTZConfiguration", token="cfg-1")
                cfg.append(element(TT, "NodeToken", "node-1"))
                source = element(TT, "VideoSource" if self.media2 else "VideoSourceConfiguration", token="vs-1")
                source.append(element(TT, "SourceToken", f"sensor-{i}"))
                if self.media2:
                    container = element(ns, "Configurations")
                    container.extend([source, cfg])
                    profile.append(container)
                else:
                    profile.extend([source, cfg])
                response.append(profile)
        elif operation == "GetConfigurationOptions":
            options = element(PTZ, "PTZConfigurationOptions")
            spaces = element(TT, "Spaces")
            for mode in ("Continuous", "Absolute", "Relative"):
                for axis in (("PanTilt", "Zoom") if self.zoom else ("PanTilt",)):
                    suffix = {"Continuous": "VelocitySpace", "Absolute": "PositionSpace",
                              "Relative": "TranslationSpace"}[mode]
                    name = mode + axis + suffix
                    s = element(TT, name)
                    s.append(element(TT, "URI", "urn:simulated:" + name))
                    for dim in (("XRange", "YRange") if axis == "PanTilt" else ("XRange",)):
                        r = element(TT, dim)
                        r.extend([element(TT, "Min", "-1"), element(TT, "Max", "1")])
                        s.append(r)
                    spaces.append(s)
            options.append(spaces)
            timeout = element(TT, "PTZTimeout")
            timeout.extend([element(TT, "Min", "PT0.01S"), element(TT, "Max", "PT10S")])
            options.append(timeout)
            response.append(options)
        elif operation == "GetNode":
            node = element(PTZ, "PTZNode", token="node-1")
            node.extend([element(TT, "MaximumNumberOfPresets", "16"),
                         element(TT, "HomeSupported", "true")])
            response.append(node)
        elif operation == "ContinuousMove":
            from .backend import duration
            timeout = next(e.text for e in fields if e.tag.endswith("}Timeout"))
            self.moving = True
            self.device_deadline = time.monotonic() + duration(timeout)
            self.move_started.set()
            if self.delay:
                # Intentional blocking wait in a simulated I/O worker, never event loop.
                threading.Event().wait(self.delay)
            if self.fail_move:
                raise TransportError("simulated reply lost after movement applied")
        elif operation == "Stop":
            if self.fail_stop:
                raise TransportError("simulated Stop failure")
            self.moving = False
        elif operation == "GetStatus":
            status = element(PTZ, "PTZStatus")
            move = element(TT, "MoveStatus")
            moving = self.moving and time.monotonic() < self.device_deadline
            move.append(element(TT, "PanTilt", "MOVING" if moving else "IDLE"))
            status.append(move)
            response.append(status)
        elif operation == "GetPresets":
            preset = element(PTZ, "Preset", token="preset-1")
            preset.append(element(TT, "Name", "Offline preset"))
            response.append(preset)
        elif operation == "SetPreset":
            response.append(element(PTZ, "PresetToken", "preset-new"))
        elif operation in {"AbsoluteMove", "RelativeMove", "GotoPreset", "GotoHomePosition",
                           "RemovePreset", "SetHomePosition", "GetNodes", "GetConfiguration"}:
            pass
        else:
            raise SoapFault(("ter:ActionNotSupported",))
        return response

    def close(self):
        self.closed = True


def simulated_backend(config):
    return OnvifBackend(config, SimulatedTransport(config))
