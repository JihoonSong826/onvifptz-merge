"""Future integration points only. None of these functions access devices."""
from dataclasses import dataclass


@dataclass(frozen=True)
class StubResult:
    feature: str
    status: str = "not_implemented"
    data: object = None


async def discover_cameras() -> StubResult:
    return StubResult("WS-Discovery", data=[])


async def open_rtsp_stream(camera_id: str, uri: str | None = None) -> StubResult:
    return StubResult("RTSP playback")


async def subscribe_events(camera_id: str) -> StubResult:
    return StubResult("ONVIF Eventing")


async def start_recording(camera_id: str) -> StubResult:
    return StubResult("Storage")


async def display_stream(camera_id: str) -> StubResult:
    return StubResult("Display")
