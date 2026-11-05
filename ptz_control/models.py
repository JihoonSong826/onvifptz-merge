from dataclasses import dataclass, field
from math import isfinite

from .errors import ConfigurationError


def finite(value: float, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ConfigurationError(f"{name} must be a finite number") from None
    if not isfinite(result):
        raise ConfigurationError(f"{name} must be a finite number")
    return result


@dataclass(frozen=True)
class Credentials:
    username: str = field(repr=False)
    password: str = field(repr=False)


@dataclass(frozen=True)
class CameraConfig:
    camera_id: str
    device_url: str
    credentials: Credentials = field(repr=False)
    profile_token: str | None = None
    video_source_token: str | None = None
    # Explicit operator-approved aliases only. No automatic NAT rewriting.
    allowed_service_hosts: tuple[str, ...] = ()
    media_version: str = "auto"  # auto, media1, media2
    socket_timeout: float = 2.0
    response_deadline: float = 5.0
    max_move_seconds: float = 1.0
    min_interval: float = 0.1
    ca_file: str | None = None
    # Absolute/relative/preset/home have no ContinuousMove Timeout parameter.
    allow_unbounded_moves: bool = False
    allow_persistent_writes: bool = False
    # Explicit (service namespace, URL) pairs from the host registry (M1).
    # Overrides replace advertised addresses, never bypass endpoint validation.
    service_urls: tuple[tuple[str, str], ...] = ()

    def __post_init__(self):
        try:
            pairs = tuple((ns, url) for ns, url in self.service_urls)
        except (TypeError, ValueError):
            raise ConfigurationError("service_urls must contain namespace/URL pairs") from None
        supported = {"http://www.onvif.org/ver10/media/wsdl",
                     "http://www.onvif.org/ver20/media/wsdl",
                     "http://www.onvif.org/ver20/ptz/wsdl"}
        if any(ns not in supported or not isinstance(url, str) or not url for ns, url in pairs):
            raise ConfigurationError("invalid service namespace or URL")
        if len({ns for ns, _ in pairs}) != len(pairs):
            raise ConfigurationError("duplicate service namespace")
        object.__setattr__(self, "service_urls", pairs)
        if not self.camera_id.strip():
            raise ConfigurationError("camera_id is required")
        if self.media_version not in {"auto", "media1", "media2"}:
            raise ConfigurationError("invalid media_version")
        for name in ("socket_timeout", "response_deadline", "max_move_seconds"):
            value = finite(getattr(self, name), name)
            if value <= 0:
                raise ConfigurationError(f"{name} must be positive")
            object.__setattr__(self, name, value)
        if finite(self.min_interval, "min_interval") < 0:
            raise ConfigurationError("min_interval must not be negative")
        object.__setattr__(self, "min_interval", finite(self.min_interval, "min_interval"))


@dataclass(frozen=True)
class AxisRange:
    minimum: float
    maximum: float

    def __post_init__(self):
        lo = finite(self.minimum, "range minimum")
        hi = finite(self.maximum, "range maximum")
        if lo >= hi:
            raise ConfigurationError("invalid axis range")

    def check(self, value: float) -> float:
        value = finite(value, "axis")
        if not self.minimum <= value <= self.maximum:
            raise ConfigurationError("axis outside advertised range")
        return value

    def velocity(self, normalized: float) -> float:
        value = finite(normalized, "velocity")
        if not -1 <= value <= 1:
            raise ConfigurationError("normalized velocity must be in [-1, 1]")
        if not self.minimum <= 0 <= self.maximum:
            raise ConfigurationError("velocity space must include zero")
        if value < 0 and self.minimum >= 0 or value > 0 and self.maximum <= 0:
            raise ConfigurationError("requested direction is unsupported")
        return value * (self.maximum if value >= 0 else -self.minimum)


@dataclass(frozen=True)
class Space:
    uri: str
    x: AxisRange
    y: AxisRange | None = None


@dataclass(frozen=True)
class Binding:
    profile_token: str
    configuration_token: str
    node_token: str
    source_token: str | None


@dataclass(frozen=True)
class Capabilities:
    binding: Binding
    continuous_pan_tilt: Space | None
    continuous_zoom: Space | None
    absolute_pan_tilt: Space | None
    absolute_zoom: Space | None
    relative_pan_tilt: Space | None
    relative_zoom: Space | None
    timeout_min: float | None
    timeout_max: float | None
    maximum_presets: int
    home_supported: bool
    auxiliary_commands: tuple[str, ...]


@dataclass(frozen=True)
class CommandResult:
    camera_id: str
    operation: str
    status: str = "accepted"  # SOAP acceptance, NOT physical completion
