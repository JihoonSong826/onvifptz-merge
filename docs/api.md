# Public API and Errors

[README](../README.md) | [Documentation index](index.md)

## Manager and controller

| API | Behavior and return value |
| --- | --- |
| `await manager.add(config)` | Query services/profiles/capabilities, check duplicates, send initial Stop; return `CameraController` |
| `manager.get(camera_id)` | Return registered controller; `NotReady` if absent |
| `await manager.remove(camera_id)` | Final Stop and cleanup; release closed registration even if Stop fails |
| `await manager.close()` | Close devices and block additions; report failures as `TransportError` |
| `await camera.close()` | Close controller; use manager removal to release its registry entry |
| `await camera.move(pan=0, tilt=0, zoom=0, seconds=0.3)` | Continuous movement; return `CommandResult` |
| `await camera.stop()` | Stop all axes, discard pending movement, bypass interval; return `CommandResult` |
| `await camera.status()` | Dictionary with position, movement status, and `utc_time` |
| `await camera.presets()` | List of dictionaries with preset `token` and `name` |
| `camera.capabilities` | Connection-time snapshot; not automatically refreshed |
| `camera.state` | `connecting`, `ready`, `faulted`, or `closed` |
| `camera.last_error` | Last recorded error type |
| `await camera.get_nodes()` | `GetNodesResponse` as `ElementTree.Element` |
| `await camera.get_configuration()` | `GetConfigurationResponse` as `ElementTree.Element` |

Movement parameters are keyword-only. `CommandResult` contains `camera_id`, `operation`, and `status="accepted"`. Movement operations use internal names such as `move` or `absolute_move`; Stop uses `"Stop"`. Map these to product-facing names explicitly. Acceptance is not physical completion.

Status preserves device coordinate strings and space URIs; missing values are `None`. Do not interpret generic position as degrees or millimeters without a device mapping. XML query results require conversion before JSON serialization.

Closing is an internal flag, not a public state value. Disable UI input when removal/shutdown starts. Stop requested during shutdown receives `NotReady`; the shutdown routine owns final Stop.

## Continuous movement

`move()` accepts normalized speeds from -1 to 1 and maps them to advertised ranges. Zero stops that axis. Supported axes are included even at zero so previous movement does not persist. Nonzero input on an unsupported axis raises `Unsupported`. Nonfinite and out-of-range values are rejected.

`seconds` cannot exceed `max_move_seconds`. If the device minimum Timeout is longer, the duration is raised to that minimum only within the safety ceiling. Local Stop is armed before network transmission. All-zero movement becomes Stop, but use `stop()` for unconditional stopping.

## Optional movement and persistent changes

| API | Meaning and conditions |
| --- | --- |
| `absolute_move(*, pan=None, tilt=None, zoom=None, watchdog_seconds=1.0)` | Device absolute-space coordinates; pan and tilt together; omitted axes unchanged |
| `relative_move(*, pan=None, tilt=None, zoom=None, watchdog_seconds=1.0)` | Device relative-space displacement, not normalized velocity |
| `goto_preset(token, *, watchdog_seconds=1.0)` | Existing device-returned preset token |
| `goto_home(*, watchdog_seconds=1.0)` | Requires home support |
| `set_preset(name, token=None)` | Create/update preset; return preset token |
| `remove_preset(token)` | Delete preset; return `None` |
| `set_home()` | Store current position as home; return `None` |

All these methods are asynchronous. Position/preset/home movement requires `allow_unbounded_moves=True`. They lack ContinuousMove's device Timeout; their watchdog only schedules a local Stop and may interrupt before arrival. A disconnected network can prevent Stop.

Preset saving/deletion and home setting require `allow_persistent_writes=True`. `SetConfiguration` and `SendAuxiliaryCommand` have no public implementation.

## Exceptions

| Exception | Meaning | Host response |
| --- | --- | --- |
| `ConfigurationError` | Invalid input, endpoint, selection, or range | Correct configuration |
| `AuthenticationError` | Credentials/permission rejected | Stop automatic retries; check account and privileges |
| `Unsupported` | Unsupported or disabled operation | Disable UI operation or review policy |
| `TransportError` | Communication failure or unconfirmed Stop | Treat outcome as uncertain; evaluate reconnection |
| `ProtocolError` | Invalid XML, response, token, or range format | Record compatibility failure |
| `SoapFault` | Device SOAP fault | Classify via `codes` and `has()`; raw vendor text is hidden |
| `NotReady` | Missing, closed, closing, or faulted controller | Check lifecycle/reference |
| `Superseded` | Pending movement replaced, canceled, or expired | Consume as input coalescing |
| `Busy` | Registration or queue capacity reached | Reduce input rate or report congestion |

## Protocol scope

SOAP 1.2, WS-Security UsernameToken PasswordDigest, HTTP Digest, HTTPS certificate validation, device time queries, GetServices, limited GetCapabilities fallback, Media1/Media2 GetProfiles, PTZ node/options queries, and the operations above are implemented. Camera time is not changed. Basic authentication and disabling certificate checks are not provided.

## Non-PTZ stubs

| Async function | Data returned |
| --- | --- |
| `discover_cameras()` | `[]` |
| `open_rtsp_stream()` | `None` |
| `subscribe_events()` | `None` |
| `start_recording()` | `None` |
| `display_stream()` | `None` |

Each returns `StubResult(status="not_implemented")`, for example:

```python
StubResult(feature="RTSP playback", status="not_implemented", data=None)
```

Stubs do not send requests or pretend that a connection succeeded. Replace them with host implementations or connect existing modules directly. Stream URI retrieval, decoding, recording, and subscriptions are unimplemented. `simulation.py` provides separate offline responses for tests and demos.

## Additional APIs in 0.2.0

| API | Result |
| --- | --- |
| `camera.snapshot()` | Local JSON-ready camera_id, state, last_error, and capabilities; no credentials and no network probe |
| `await camera.get_nodes_data()` | Namespace-aware dictionary representation of GetNodesResponse |
| `await camera.get_configuration_data()` | Namespace-aware dictionary representation of GetConfigurationResponse |
| `zeep_backend_factory(wsdl_directory)` | Optional backend factory imported from ptz_control.zeep_transport |

XML data shape: `{ "tag": "{namespace}name", "attributes": {}, "text": null, "children": [] }`.
Repeated child elements stay separate and ordered. This shape is generic XML data,
not a flattened ONVIF-specific JSON schema. Host adapters must map fields explicitly.
`service_urls` is described in [integration](integration.md). Existing APIs are unchanged.
