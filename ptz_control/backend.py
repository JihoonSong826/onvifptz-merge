"""Synchronous protocol adapter; called only by a camera's dedicated worker."""
from datetime import datetime, timezone
import re
import xml.etree.ElementTree as ET

from .errors import ConfigurationError, ProtocolError, SoapFault, Unsupported, AuthenticationError
from .models import AxisRange, Binding, CameraConfig, Capabilities, Space, finite
from .soap import (DEVICE, MEDIA1, MEDIA2, PTZ, TT, SoapTransport,
                   child, children, element, text)


def duration(value: str | None) -> float | None:
    if value is None:
        return None
    # Years/months have no fixed duration and are inappropriate PTZ timeouts.
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?", value)
    if not m or not any(m.groups()):
        raise ProtocolError("invalid PTZ timeout duration")
    d, h, minute, s = (float(x or 0) for x in m.groups())
    return finite(d * 86400 + h * 3600 + minute * 60 + s, "timeout")


def required(value, name):
    if value is None or value == "":
        raise ProtocolError(f"missing {name}")
    return value


class OnvifBackend:
    def __init__(self, config: CameraConfig, transport=None):
        self.config = config
        self.transport = transport or SoapTransport(config)
        self.ptz_url = None
        self.media_url = None
        self.media_ns = None
        self.capabilities = None
        self.configuration = None

    def _device(self, operation, *fields, authenticated=True):
        return self.transport.call(self.config.device_url, DEVICE, operation, fields,
                                   authenticated=authenticated)

    def _ptz(self, operation, *fields):
        if self.ptz_url is None:
            raise ConfigurationError("PTZ service is not bound")
        return self.transport.call(self.ptz_url, PTZ, operation, fields)

    def _profile(self):
        return element(PTZ, "ProfileToken", self.capabilities.binding.profile_token)

    def connect(self) -> Capabilities:
        overrides = {ns: self.transport.validate_endpoint(url)
                     for ns, url in self.config.service_urls}
        # A read-only clock probe: never change the device's clock or NTP setup.
        try:
            clock = self._device("GetSystemDateAndTime", authenticated=False)
        except AuthenticationError:
            clock = self._device("GetSystemDateAndTime")
        except SoapFault as exc:
            if not exc.has("ActionNotSupported", "OptionalActionNotImplemented"):
                raise
            clock = None
        if clock is not None:
            dt = child(clock, "SystemDateAndTime")
            utc = child(dt, "UTCDateTime") if dt is not None else None
            if utc is not None:
                try:
                    values = [int(text(utc, block, key)) for block, key in
                              [("Date", "Year"), ("Date", "Month"), ("Date", "Day"),
                               ("Time", "Hour"), ("Time", "Minute"), ("Time", "Second")]]
                    self.transport.clock_offset = (datetime(*values, tzinfo=timezone.utc)
                                                   - datetime.now(timezone.utc)).total_seconds()
                except (TypeError, ValueError, OverflowError):
                    raise ProtocolError("invalid camera UTC clock") from None

        endpoints = {}
        try:
            response = self._device("GetServices", element(DEVICE, "IncludeCapability", "false"))
            for service in children(response, "Service"):
                ns, url = text(service, "Namespace"), text(service, "XAddr")
                if ns in (PTZ, MEDIA1, MEDIA2) and url:
                    endpoints[ns] = self.transport.validate_endpoint(overrides.get(ns, url))
        except SoapFault as exc:
            if not exc.has("ActionNotSupported", "OptionalActionNotImplemented"):
                raise
        endpoints.update(overrides)
        if PTZ not in endpoints or not any(n in endpoints for n in (MEDIA1, MEDIA2)):
            response = self._device("GetCapabilities", element(DEVICE, "Category", "All"))
            caps = child(response, "Capabilities")
            if caps is not None:
                for name, ns in (("PTZ", PTZ), ("Media", MEDIA1)):
                    url = text(caps, name, "XAddr")
                    if url and ns not in endpoints:
                        endpoints[ns] = self.transport.validate_endpoint(url)
        if PTZ not in endpoints:
            raise Unsupported("device does not advertise PTZ")
        self.ptz_url = endpoints[PTZ]
        preference = {"auto": (MEDIA2, MEDIA1), "media1": (MEDIA1,), "media2": (MEDIA2,)}
        profiles = None
        for ns in preference[self.config.media_version]:
            if ns not in endpoints:
                continue
            fields = [element(ns, "Type", "All")] if ns == MEDIA2 else []
            try:
                response = self.transport.call(endpoints[ns], ns, "GetProfiles", fields)
            except SoapFault as exc:
                if exc.has("ActionNotSupported", "OptionalActionNotImplemented"):
                    continue
                raise
            self.media_url, self.media_ns = endpoints[ns], ns
            profiles = children(response, "Profiles")
            break
        if profiles is None:
            raise Unsupported("no usable advertised Media service")

        candidates = []
        for profile in profiles:
            if self.media_ns == MEDIA1:
                cfg = child(profile, "PTZConfiguration")
                source = text(profile, "VideoSourceConfiguration", "SourceToken")
            else:
                configurations = child(profile, "Configurations")
                cfg = child(configurations, "PTZ") if configurations is not None else None
                source = (text(configurations, "VideoSource", "SourceToken")
                          if configurations is not None else None)
            if cfg is None:
                continue
            token = required(profile.get("token"), "profile token")
            if self.config.profile_token is not None and token != self.config.profile_token:
                continue
            if self.config.video_source_token is not None and source != self.config.video_source_token:
                continue
            candidates.append((profile, cfg, source))
        if not candidates:
            raise Unsupported("no matching PTZ-enabled media profile")
        if len(candidates) != 1:
            raise ConfigurationError("multiple PTZ profiles: select profile_token or video_source_token")
        profile, cfg, source = candidates[0]
        binding = Binding(profile.get("token"), required(cfg.get("token"), "configuration token"),
                          required(text(cfg, "NodeToken"), "node token"), source)
        self.configuration = cfg
        options_response = self._ptz("GetConfigurationOptions",
                                    element(PTZ, "ConfigurationToken", binding.configuration_token))
        options = required(child(options_response, "PTZConfigurationOptions"), "configuration options")
        node_response = self._ptz("GetNode", element(PTZ, "NodeToken", binding.node_token))
        node = required(child(node_response, "PTZNode"), "PTZ node")
        if node.get("token") != binding.node_token:
            raise ProtocolError("PTZ node token mismatch")
        spaces = required(child(options, "Spaces"), "PTZ spaces")

        def space(name, default_name):
            available = children(spaces, name)
            if not available:
                return None
            default_uri = text(cfg, default_name)
            picked = next((e for e in available if text(e, "URI") == default_uri), available[0])
            try:
                x = AxisRange(float(text(picked, "XRange", "Min")),
                              float(text(picked, "XRange", "Max")))
                y = None
                if "PanTilt" in name:
                    y = AxisRange(float(text(picked, "YRange", "Min")),
                                  float(text(picked, "YRange", "Max")))
                return Space(required(text(picked, "URI"), "space URI"), x, y)
            except (TypeError, ValueError):
                raise ProtocolError("invalid PTZ axis range") from None

        lo = duration(text(options, "PTZTimeout", "Min"))
        hi = duration(text(options, "PTZTimeout", "Max"))
        if (lo is None) != (hi is None) or (lo is not None and (lo < 0 or hi < lo)):
            raise ProtocolError("invalid PTZ timeout range")
        try:
            presets = int(text(node, "MaximumNumberOfPresets", default="0"))
        except ValueError:
            raise ProtocolError("invalid preset count") from None
        self.capabilities = Capabilities(
            binding,
            space("ContinuousPanTiltVelocitySpace", "DefaultContinuousPanTiltVelocitySpace"),
            space("ContinuousZoomVelocitySpace", "DefaultContinuousZoomVelocitySpace"),
            space("AbsolutePanTiltPositionSpace", "DefaultAbsolutePantTiltPositionSpace"),
            space("AbsoluteZoomPositionSpace", "DefaultAbsoluteZoomPositionSpace"),
            space("RelativePanTiltTranslationSpace", "DefaultRelativePanTiltTranslationSpace"),
            space("RelativeZoomTranslationSpace", "DefaultRelativeZoomTranslationSpace"),
            lo, hi, presets, text(node, "HomeSupported") in ("true", "1"),
            tuple(e.text for e in children(node, "AuxiliaryCommands") if e.text))
        return self.capabilities

    @property
    def physical_key(self):
        return (self.ptz_url, self.capabilities.binding.node_token)

    def validate_move(self, pan, tilt, zoom, seconds):
        caps = self.capabilities
        seconds = finite(seconds, "seconds")
        if not 0 < seconds <= self.config.max_move_seconds:
            raise ConfigurationError("move duration exceeds configured safety limit")
        if caps.timeout_min is None or caps.timeout_max is None or caps.timeout_max <= 0:
            raise Unsupported("continuous movement requires an advertised device timeout range")
        device_timeout = max(seconds, caps.timeout_min)
        if device_timeout > min(caps.timeout_max, self.config.max_move_seconds):
            raise ConfigurationError("device timeout cannot meet the configured safety limit")
        velocity = element(PTZ, "Velocity")
        pan, tilt, zoom = [finite(v, "velocity") for v in (pan, tilt, zoom)]
        if caps.continuous_pan_tilt:
            s = caps.continuous_pan_tilt
            velocity.append(element(TT, "PanTilt", x=s.x.velocity(pan),
                                    y=s.y.velocity(tilt), space=s.uri))
        elif pan or tilt:
            raise Unsupported("continuous pan/tilt is unsupported")
        if caps.continuous_zoom:
            s = caps.continuous_zoom
            velocity.append(element(TT, "Zoom", x=s.x.velocity(zoom), space=s.uri))
        elif zoom:
            raise Unsupported("continuous zoom is unsupported")
        if len(velocity) == 0:
            raise Unsupported("continuous movement is unsupported")
        return velocity, device_timeout

    def move(self, pan, tilt, zoom, seconds):
        velocity, timeout = self.validate_move(pan, tilt, zoom, seconds)
        self._ptz("ContinuousMove", self._profile(), velocity,
                  element(PTZ, "Timeout", f"PT{timeout:.6f}S"))

    def stop(self):
        # Omitting BOTH optional filters is the standard all-axes Stop.
        return self._ptz("Stop", self._profile())

    def status(self):
        response = self._ptz("GetStatus", self._profile())
        status = required(child(response, "PTZStatus"), "PTZStatus")
        result = {"pan_tilt": None, "zoom": None, "pan_tilt_motion": None,
                  "zoom_motion": None, "utc_time": text(status, "UtcTime")}
        position = child(status, "Position")
        if position is not None:
            for tag, key in (("PanTilt", "pan_tilt"), ("Zoom", "zoom")):
                axis = child(position, tag)
                if axis is not None:
                    result[key] = dict(axis.attrib)  # values stay in device units
        result["pan_tilt_motion"] = text(status, "MoveStatus", "PanTilt")
        result["zoom_motion"] = text(status, "MoveStatus", "Zoom")
        return result

    def presets(self):
        response = self._ptz("GetPresets", self._profile())
        return [{"token": e.get("token"), "name": text(e, "Name")}
                for e in children(response, "Preset")]

    def _coordinate(self, mode, pan, tilt, zoom):
        if not self.config.allow_unbounded_moves:
            raise Unsupported("enable allow_unbounded_moves for motion without a device watchdog")
        caps = self.capabilities
        pt = getattr(caps, mode + "_pan_tilt")
        zs = getattr(caps, mode + "_zoom")
        vector = element(PTZ, "Position" if mode == "absolute" else "Translation")
        if (pan is None) != (tilt is None):
            raise ConfigurationError("pan and tilt must be specified together")
        if pan is not None:
            if pt is None:
                raise Unsupported("requested pan/tilt space is unsupported")
            vector.append(element(TT, "PanTilt", x=pt.x.check(pan), y=pt.y.check(tilt), space=pt.uri))
        if zoom is not None:
            if zs is None:
                raise Unsupported("requested zoom space is unsupported")
            vector.append(element(TT, "Zoom", x=zs.x.check(zoom), space=zs.uri))
        if not len(vector):
            raise ConfigurationError("at least one axis is required")
        return vector

    def absolute_move(self, pan=None, tilt=None, zoom=None):
        vector = self._coordinate("absolute", pan, tilt, zoom)
        self._ptz("AbsoluteMove", self._profile(), vector)

    def relative_move(self, pan=None, tilt=None, zoom=None):
        vector = self._coordinate("relative", pan, tilt, zoom)
        self._ptz("RelativeMove", self._profile(), vector)

    def goto_preset(self, token):
        if not self.config.allow_unbounded_moves:
            raise Unsupported("preset movement without a device watchdog is disabled")
        if not token or self.capabilities.maximum_presets <= 0:
            raise Unsupported("preset movement is unavailable")
        self._ptz("GotoPreset", self._profile(), element(PTZ, "PresetToken", token))

    def goto_home(self):
        if not self.config.allow_unbounded_moves or not self.capabilities.home_supported:
            raise Unsupported("home movement is unavailable or disabled")
        self._ptz("GotoHomePosition", self._profile())

    def set_preset(self, name, token=None):
        if not self.config.allow_persistent_writes or self.capabilities.maximum_presets <= 0:
            raise Unsupported("persistent preset writes are unavailable or disabled")
        fields = [self._profile(), element(PTZ, "PresetName", name)]
        if token is not None:
            fields.append(element(PTZ, "PresetToken", token))
        return text(self._ptz("SetPreset", *fields), "PresetToken")

    def remove_preset(self, token):
        if not self.config.allow_persistent_writes:
            raise Unsupported("persistent writes are disabled")
        self._ptz("RemovePreset", self._profile(), element(PTZ, "PresetToken", token))

    def set_home(self):
        if not self.config.allow_persistent_writes or not self.capabilities.home_supported:
            raise Unsupported("home writes are unavailable or disabled")
        self._ptz("SetHomePosition", self._profile())

    def get_nodes(self):
        return self._ptz("GetNodes")

    def get_configuration(self):
        return self._ptz("GetConfiguration", element(
            PTZ, "PTZConfigurationToken", self.capabilities.binding.configuration_token))

    def close(self):
        self.transport.close()
