# Integration and Connection Contract

[README](../README.md) | [Documentation index](index.md)

## Information required from the connection owner

Provide a unique `camera_id`, reachable ONVIF Device URL, credentials with PTZ privileges, and the mapping from displayed video to profile/source token. Report address, credential, and profile changes. Supply approved service-host aliases and a trusted CA file when needed.

Account creation, device initialization, password rotation, IP changes, and video playback belong to the host. ONVIF does not assign a universal username or password. Use the local device or dedicated ONVIF account configured for the endpoint, not an assumed cloud account.

## CameraConfig

| Field | Default / type | Integration responsibility |
| --- | --- | --- |
| `camera_id` | Required string | Unique identifier shared by UI, registry, video, and PTZ |
| `device_url` | Required HTTP(S) URL | Actual Device service address, not an RTSP URL |
| `credentials` | Required `Credentials` | Inject username/password from the host secret store |
| `profile_token` | `None` | Explicit device-returned profile when selection is ambiguous |
| `video_source_token` | `None` | Filter by intended video source or NVR channel |
| `media_version` | `"auto"` | Prefer Media2, or force `"media1"` / `"media2"` |
| `allowed_service_hosts` | Empty tuple | Approve separately advertised service hosts |
| `socket_timeout` | `2.0` seconds | Individual socket operation timeout |
| `response_deadline` | `5.0` seconds | Connected response budget including authentication retries |
| `max_move_seconds` | `1.0` seconds | Safety ceiling for movement and device Timeout |
| `min_interval` | `0.1` seconds | Minimum interval between movement starts; Stop bypasses it |
| `ca_file` | `None` | Trust file for a private HTTPS CA |
| `allow_unbounded_moves` | `False` | Enable position/preset/home moves without device Timeout |
| `allow_persistent_writes` | `False` | Enable preset saving/deletion and home setting |

Multiple matching profiles cause `ConfigurationError`; the first profile is not selected arbitrarily. A profile or source filter must resolve to one PTZ profile.

`Credentials` holds in-memory values. Fields are excluded from its representation but are not encrypted or automatically erased from memory. Secret storage and rotation remain host responsibilities. Do not embed credentials in URLs.

## Connection sequence

```text
Host supplies camera_id, Device URL, credentials, and video mapping
  -> await manager.add(config)
     -> GetSystemDateAndTime: authentication clock adjustment
     -> GetServices, or supported GetCapabilities fallback
     -> Media2 or Media1 GetProfiles
     -> select PTZConfiguration and NodeToken
     -> GetConfigurationOptions and GetNode
     -> reject duplicate physical PTZ binding
     -> initial Stop
  -> ready: enable UI operations based on capabilities
  -> move request accepted
  -> button release or safety deadline: Stop
  -> address/account change or failure: remove, then add
```

`Binding` holds `profile_token`, `configuration_token`, `node_token`, and `source_token`. ProfileToken targets movement/Stop. GetConfiguration uses `PTZConfigurationToken`, while GetConfigurationOptions uses `ConfigurationToken`. The backend handles these XML distinctions.

## Reconnection and lifecycle

Automatic backoff reconnection is not implemented. Distinguish authentication errors from transport errors and decide when to re-register. Do not retry credentials indefinitely or replay old movements.

`remove()` attempts final Stop and tears down the worker. If final Stop fails, it reports an exception but releases the closed registration so a new `add()` can succeed. Physical stopping remains uncertain until verified; the new connection starts with another Stop.

Replace old controller references and discard commands from an earlier UI generation. If shutdown begins during initialization, initialization is cleaned up without leaving a new ready controller behind. Shutdown tracks completion of `add()`, not the entire lifetime of the calling service task.

## Application example

```python
import asyncio
from ptz_control import CameraManager, CameraConfig, Credentials

async def run(secret_store):
    config = CameraConfig(
        camera_id="cam-01",
        device_url="http://192.168.10.21/onvif/device_service",
        credentials=Credentials(secret_store.username, secret_store.password),
        profile_token="actual-profile-token",
    )
    async with CameraManager(max_cameras=32) as manager:
        camera = await manager.add(config)
        try:
            result = await camera.move(pan=0.1, seconds=0.2)
            # accepted means SOAP acceptance, not physical completion.
            await asyncio.sleep(0.25)
            status = await camera.status()
        finally:
            await camera.stop()
```

`secret_store` represents the host's secret lookup result; the package does not implement it. Replace example addresses and tokens with actual device values. `asyncio.sleep()` yields only this coroutine. Actor intervals use asynchronous events and monotonic time.

For independent devices:

```python
async def control_two(config_a, config_b):
    async with CameraManager() as manager:
        a, b = await asyncio.gather(manager.add(config_a), manager.add(config_b))
        try:
            await asyncio.gather(
                a.move(pan=0.15, seconds=0.3),
                b.move(tilt=-0.15, seconds=0.2),
            )
            await asyncio.sleep(0.35)
        finally:
            await asyncio.gather(a.stop(), b.stop())
```

## UI integration rules

Create and use controllers within one asyncio loop. If the GUI runs in another thread, bridge requests to that loop rather than accessing controller internals or the HTTP opener directly. Do not create a new loop with `asyncio.run()` for every click.

Rate-limit joystick input. Avoid unbounded `create_task()` calls and consume each result or `Superseded` exception. Send explicit Stop on button release, focus loss, tile changes, and user-session termination. Control ownership across users and other applications belongs to the host.

## Real-camera example

Enable ONVIF and prepare an account with PTZ privileges. For NVR access, use the NVR endpoint/account and the target channel's profile.

```powershell
$env:ONVIF_DEVICE_URL = "http://192.168.10.21/onvif/device_service"
$env:ONVIF_USERNAME = "ptz_operator"
$env:ONVIF_PROFILE_TOKEN = "actual-profile-token"
# Inject ONVIF_PASSWORD through a secure session input or secret store.
python -m examples.real_camera
```

`ONVIF_PASSWORD` must also be set. Environment variables are a development injection mechanism; production should use an appropriate credential store. The URL path is an example and must match the device.

**Without `--move`, the example still sends Stop on connection and shutdown.** Coordinate ownership first. Use `python -m examples.real_camera --move` only when a short low-speed physical movement is intended.

## M1 service endpoint contract in 0.2.0

`CameraConfig.service_urls` is an immutable tuple of `(service_namespace, URL)` pairs.
Only PTZ, Media1, and Media2 namespaces are accepted; duplicates fail. Overrides are
validated before device I/O, replace corresponding advertised addresses, and can
supply missing service endpoints. They do not skip Device/profile/capability queries.
An unreachable Device endpoint still prevents connection.

```python
from ptz_control.soap import PTZ, MEDIA2

config = CameraConfig(
    camera_id="cam-01",
    device_url="https://camera.example/onvif/device_service",
    credentials=Credentials(username, password),
    profile_token="device-returned-token",
    media_version="media2",
    service_urls=(
        (PTZ, "https://camera.example/onvif/ptz_service"),
        (MEDIA2, "https://camera.example/onvif/media2_service"),
    ),
)
```

Use actual M1-resolved values. Different target hosts still require explicit
`allowed_service_hosts`; HTTPS-to-HTTP downgrade stays forbidden. Match profile
tokens to the selected Media version and video source. A replacement PTZ URL does
not establish that two aliases are the same motor; M1 still owns that mapping.

`camera.snapshot()` returns a JSON-ready local snapshot without credentials.
`await camera.get_nodes_data()` and `await camera.get_configuration_data()` preserve
namespace-qualified XML tags, attributes, text, and repeated children in dictionaries.
The original XML-returning methods remain available. These query payloads may include
device-provided metadata; the host decides what to expose externally.

PTZ registration still sends initial Stop. M1 should retain controllers, not add/remove
for every status poll. Discovery, Stream URI, MQTT health, and control ownership remain
M1/host responsibilities. The PTZ library's CameraManager is not a replacement for M1.
