# Concurrency and Safety

[README](../README.md) | [Documentation index](index.md)

## Scheduling

- Each camera has one asynchronous actor and one I/O worker. Camera A's network wait does not block camera B's event-loop execution. Shared NVR resources can still impose limits.
- The normal queue holds at most eight entries. Only the latest pending movement is kept; replaced callers receive `Superseded`.
- Movement expires after its queue validity window rather than replaying stale joystick input.
- Stop clears pending movement and bypasses the movement interval. It cannot interrupt an RPC already executing in that worker.
- Intervals use monotonic time and asyncio events, without a global blocking sleep.
- ContinuousMove always includes an advertised, bounded device Timeout. The local Stop deadline is armed before transmission.
- Expired Stop takes priority over status and new requests. Executing a new movement replaces the local deadline.
- Cancellation, lost movement responses, and shutdown cause a Stop attempt. Movement is not automatically retried.
- Movement or Stop failure faults the controller and blocks new movement. Stop can be retried while the actor is active. Reconnect through remove followed by a new add.
- Final Stop failure is reported through errors rather than presented as successful stopping.

## Time limits

| Setting | Purpose |
| --- | --- |
| `min_interval` | Minimum time between movement starts; Stop bypasses it |
| `seconds` | Requested continuous duration; affects device Timeout and local Stop |
| `max_move_seconds` | Safety ceiling; default 1.0 seconds |
| `socket_timeout` | Individual socket operation timeout |
| `response_deadline` | Connected response budget for headers, body, and authentication retries |
| `watchdog_seconds` | Local Stop deadline for optional position/preset/home moves |

If the device minimum Timeout exceeds the safety ceiling, movement is rejected. Missing advertised Timeout support prevents the normal bounded continuous-movement path.

A watchdog shuts down the connected socket at the response deadline, even when slowly arriving headers avoid individual read timeouts. This is not a hard deadline for DNS, OS connection setup, or initial TLS negotiation. Remaining budget is checked after connection completes.

Python worker threads are not forcibly terminated. `close()` waits for active I/O to return. Products needing strict termination deadlines should isolate transport in per-camera processes.

## Physical safety and ownership

If the application or network stops completely, local Stop cannot be delivered. Device adherence to ContinuousMove Timeout is essential and requires hardware testing. SOAP acceptance does not establish that the motor stopped.

Absolute/relative/preset/home movement lacks that device Timeout argument and is disabled by default. Its local watchdog cannot guarantee stopping after disconnection. Persistent preset/home writes require a separate option.

The host arbitrates user leases, tracking priorities, and other clients. The library serializes its requests but does not lock out other camera-control programs. Send Stop on button release, focus loss, tile changes, and session termination. Connection and shutdown also send Stop, so coordinate ownership first.

Cancellation of a coroutine does not cancel transmitted physical movement. Treat response loss as an uncertain outcome and never replay movement automatically after reconnection. During shutdown, new Stop requests receive `NotReady`; shutdown itself owns final Stop.
