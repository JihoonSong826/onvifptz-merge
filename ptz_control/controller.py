"""Async facade: one bounded mailbox and one I/O worker per physical PTZ.

No blocking sleep on the event loop. Stop clears pending movement and bypasses
the normal interval. A sent request cannot be recalled; device Timeout is vital.
"""
import asyncio
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
import copy

from .backend import OnvifBackend
from .errors import Busy, ConfigurationError, NotReady, PtzError, Superseded, TransportError
from .models import CameraConfig, CommandResult, finite


@dataclass
class _Command:
    operation: str
    args: tuple
    future: asyncio.Future
    movement: bool = False
    seconds: float = 0
    expires: float = 0


class CameraController:
    """Construct via CameraManager.add; public methods run on one asyncio loop."""

    def __init__(self, config, backend):
        self.config = config
        self._backend = backend
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ptz-io")
        self._loop = asyncio.get_running_loop()
        self._pending = deque()
        self._stop_waiters = []
        self._stop_requested = False
        self._wake = asyncio.Event()
        self._task = None
        self._active_command = None
        self._close_task = None
        self._closing = False
        self._deadline = None
        self._next_move = 0.0
        self.state = "connecting"
        self.last_error = None  # exception class name only
        self._stop_error = None
        self.capabilities = None

    async def _rpc(self, operation, *args):
        fn = getattr(self._backend, operation)
        try:
            return await self._loop.run_in_executor(self._executor, partial(fn, *args))
        except PtzError:
            raise
        except Exception:
            raise TransportError("PTZ worker operation failed") from None

    async def _start(self):
        self.capabilities = await self._rpc("connect")

    async def _activate(self):
        # Only after Manager has acquired exclusive ownership of the physical PTZ.
        await self._rpc("stop")
        self.state = "ready"
        self._task = asyncio.create_task(self._run_guarded(), name=f"ptz-{self.config.camera_id}")

    def _new_future(self):
        future = self._loop.create_future()
        # Observe exceptions even if the caller abandons its awaited request.
        future.add_done_callback(lambda f: None if f.cancelled() else f.exception())
        return future

    @staticmethod
    def _finish(future, result=None, error=None):
        if not future.done():
            if error is None:
                future.set_result(result)
            else:
                # Do not expose the running actor's traceback frames to callers.
                future.set_exception(copy.copy(error).with_traceback(None))

    def _clear_moves(self):
        remaining = deque()
        for cmd in self._pending:
            if cmd.movement:
                self._finish(cmd.future, error=Superseded("movement superseded by Stop or newer input"))
            else:
                remaining.append(cmd)
        self._pending = remaining

    def _request_stop(self, future=None):
        self._clear_moves()
        self._stop_requested = True
        if future is not None:
            self._stop_waiters.append(future)
        self._wake.set()

    async def _submit(self, operation, args=(), *, movement=False, seconds=0):
        if asyncio.get_running_loop() is not self._loop:
            raise ConfigurationError("controller must be used on its owning event loop")
        if self._closing or self.state != "ready" or self._task is None or self._task.done():
            raise NotReady("camera is not ready; remove and reconnect after a fault")
        if movement:
            self._clear_moves()  # latest unsent movement wins; never replay a backlog
        if len(self._pending) >= 8:
            raise Busy("camera command queue is full")
        future = self._new_future()
        self._pending.append(_Command(operation, args, future, movement, seconds,
                                      self._loop.time() + max(1.0, self.config.max_move_seconds)))
        self._wake.set()
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            future.cancel()
            if movement:
                self._request_stop()
            raise

    async def move(self, *, pan=0.0, tilt=0.0, zoom=0.0, seconds=0.3):
        """Normalized velocities [-1, 1]. Returns acceptance, not completion."""
        if self.capabilities is None:
            raise NotReady("camera is not connected")
        pan, tilt, zoom = (finite(v, "velocity") for v in (pan, tilt, zoom))
        seconds = finite(seconds, "seconds")
        # Pure validation before admission. Zero vectors still send Stop.
        self._backend.validate_move(pan, tilt, zoom, seconds)
        if not any((pan, tilt, zoom)):
            return await self.stop()
        return await self._submit("move", (pan, tilt, zoom, seconds), movement=True, seconds=seconds)

    async def stop(self):
        if self._closing or self.state == "closed" or self._task is None or self._task.done():
            raise NotReady("camera is closed or not connected")
        future = self._new_future()
        self._request_stop(future)
        return await asyncio.shield(future)

    async def status(self):
        return await self._submit("status")

    async def presets(self):
        return await self._submit("presets")

    async def absolute_move(self, *, pan=None, tilt=None, zoom=None, watchdog_seconds=1.0):
        self._backend._coordinate("absolute", pan, tilt, zoom)
        return await self._position_move("absolute_move", (pan, tilt, zoom), watchdog_seconds)

    async def relative_move(self, *, pan=None, tilt=None, zoom=None, watchdog_seconds=1.0):
        self._backend._coordinate("relative", pan, tilt, zoom)
        return await self._position_move("relative_move", (pan, tilt, zoom), watchdog_seconds)

    async def goto_preset(self, token, *, watchdog_seconds=1.0):
        return await self._position_move("goto_preset", (token,), watchdog_seconds)

    async def goto_home(self, *, watchdog_seconds=1.0):
        return await self._position_move("goto_home", (), watchdog_seconds)

    async def _position_move(self, operation, args, seconds):
        seconds = finite(seconds, "watchdog_seconds")
        if not 0 < seconds <= self.config.max_move_seconds:
            raise ConfigurationError("watchdog exceeds configured safety limit")
        return await self._submit(operation, args, movement=True, seconds=seconds)

    async def set_preset(self, name, token=None):
        return await self._submit("set_preset", (name, token))

    async def remove_preset(self, token):
        return await self._submit("remove_preset", (token,))

    async def set_home(self):
        return await self._submit("set_home")

    async def get_nodes(self):
        return await self._submit("get_nodes")

    async def get_configuration(self):
        return await self._submit("get_configuration")

    def snapshot(self):
        """JSON-ready local metadata; no network probe or credential fields."""
        from .integration import controller_snapshot
        return controller_snapshot(self)

    async def get_nodes_data(self):
        from .integration import xml_data
        return xml_data(await self.get_nodes())

    async def get_configuration_data(self):
        from .integration import xml_data
        return xml_data(await self.get_configuration())

    async def _do_stop(self):
        self._stop_requested = False
        self._deadline = None
        waiters, self._stop_waiters = self._stop_waiters, []
        try:
            await self._rpc("stop")
        except PtzError as exc:
            self.state = "faulted"
            self._stop_error = exc
            self.last_error = type(exc).__name__
            for future in waiters:
                self._finish(future, error=exc)
        else:
            self._stop_error = None
            result = CommandResult(self.config.camera_id, "Stop")
            for future in waiters:
                self._finish(future, result)

    async def _run(self):
        while True:
            self._wake.clear()
            now = self._loop.time()
            if self._stop_requested or self._deadline is not None and now >= self._deadline:
                await self._do_stop()
                continue
            if self._closing:
                for cmd in self._pending:
                    self._finish(cmd.future, error=NotReady("camera is closing"))
                self._pending.clear()
                return
            if self._pending:
                cmd = self._pending[0]
                if cmd.future.cancelled():
                    self._pending.popleft()
                    continue
                if self.state != "ready":
                    self._pending.popleft()
                    self._finish(cmd.future, error=NotReady("camera is faulted"))
                    continue
                if cmd.movement and now >= cmd.expires:
                    self._pending.popleft()
                    self._finish(cmd.future, error=Superseded("movement expired in queue"))
                    continue
                if not cmd.movement or now >= self._next_move:
                    self._pending.popleft()
                    self._active_command = cmd
                    if cmd.movement:
                        self._deadline = now + cmd.seconds  # arm BEFORE network request
                        self._next_move = now + self.config.min_interval
                    try:
                        result = await self._rpc(cmd.operation, *cmd.args)
                    except PtzError as exc:
                        self._finish(cmd.future, error=exc)
                        self.last_error = type(exc).__name__
                        # A movement might have been applied despite failure.
                        if cmd.movement:
                            self.state = "faulted"
                            self._request_stop()
                    else:
                        if cmd.movement:
                            result = CommandResult(self.config.camera_id, cmd.operation)
                        self._finish(cmd.future, result)
                    self._active_command = None
                    continue
            deadlines = [v for v in (self._deadline,) if v is not None]
            if self._pending and self._pending[0].movement:
                deadlines.extend([self._next_move, self._pending[0].expires])
            delay = max(0, min(deadlines) - self._loop.time()) if deadlines else None
            try:
                if delay is None:
                    await self._wake.wait()
                else:
                    await asyncio.wait_for(self._wake.wait(), timeout=delay)
            except TimeoutError:
                pass

    async def _run_guarded(self):
        try:
            await self._run()
        except Exception:
            self.state = "faulted"
            self.last_error = "InternalActorError"
            error = TransportError("PTZ actor failed; reconnect required")
            if self._active_command is not None:
                self._finish(self._active_command.future, error=error)
            for cmd in self._pending:
                self._finish(cmd.future, error=error)
            self._pending.clear()
            self._request_stop()
            await self._do_stop()

    async def _close(self):
        self._closing = True
        try:
            if self._task is not None:
                self._request_stop()
                try:
                    await self._task
                finally:
                    # Settle every waiter even if an unexpected actor bug occurs.
                    for cmd in self._pending:
                        self._finish(cmd.future, error=NotReady("camera is closing"))
                    self._pending.clear()
                    for future in self._stop_waiters:
                        self._finish(future, error=NotReady("camera is closing"))
                    self._stop_waiters.clear()
        finally:
            try:
                await self._rpc("close")
            finally:
                self._executor.shutdown(wait=False, cancel_futures=True)
                self.state = "closed"
        if self._stop_error is not None:
            raise TransportError("closed worker but final Stop was not acknowledged") from None

    async def close(self):
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close())
        await asyncio.shield(self._close_task)


class CameraManager:
    def __init__(self, *, max_cameras=32, backend_factory=OnvifBackend):
        if not isinstance(max_cameras, int) or max_cameras <= 0:
            raise ConfigurationError("max_cameras must be a positive integer")
        self.max_cameras = max_cameras
        self._factory = backend_factory
        self._cameras = {}
        self._reserved_ids = set()
        self._keys = {}
        self._closed = False
        self._adding = set()

    async def add(self, config: CameraConfig) -> CameraController:
        if self._closed:
            raise NotReady("manager is closed")
        if config.camera_id in self._reserved_ids:
            raise ConfigurationError("camera_id already registered or connecting")
        if len(self._reserved_ids) >= self.max_cameras:
            raise Busy("camera capacity reached")
        self._reserved_ids.add(config.camera_id)
        add_finished = asyncio.get_running_loop().create_future()
        self._adding.add(add_finished)
        camera = None
        key = None
        try:
            camera = CameraController(config, self._factory(config))
            # Shield initialization so cancellation cannot abandon a live I/O request.
            start = asyncio.create_task(camera._start())
            try:
                await asyncio.shield(start)
            except asyncio.CancelledError:
                try:
                    await start
                except Exception:
                    pass
                raise
            if self._closed:
                raise NotReady("manager closed during camera connection")
            key = camera._backend.physical_key
            if key in self._keys:
                raise ConfigurationError("physical PTZ already registered; share its controller")
            self._keys[key] = config.camera_id
            activation = asyncio.create_task(camera._activate())
            try:
                await asyncio.shield(activation)
            except asyncio.CancelledError:
                try:
                    await activation
                except Exception:
                    pass
                raise
            if self._closed:
                raise NotReady("manager closed during activation")
            self._cameras[config.camera_id] = camera
            return camera
        except BaseException:
            try:
                if camera is not None:
                    await camera.close()
            finally:
                if key is not None and self._keys.get(key) == config.camera_id:
                    self._keys.pop(key, None)
                self._reserved_ids.discard(config.camera_id)
            raise
        finally:
            self._adding.discard(add_finished)
            if not add_finished.done():
                add_finished.set_result(None)

    def get(self, camera_id):
        try:
            return self._cameras[camera_id]
        except KeyError:
            raise NotReady("camera is not registered") from None

    async def remove(self, camera_id):
        camera = self.get(camera_id)
        try:
            await camera.close()
        finally:
            # A cancellation must not permit re-registration while old I/O still runs.
            if camera.state == "closed" and self._cameras.get(camera_id) is camera:
                self._cameras.pop(camera_id, None)
                self._keys.pop(camera._backend.physical_key, None)
                self._reserved_ids.discard(camera_id)

    async def close(self):
        self._closed = True
        if self._adding:
            await asyncio.gather(*list(self._adding), return_exceptions=True)
        # Each camera closes independently even if another camera fails.
        results = await asyncio.gather(*(c.close() for c in self._cameras.values()),
                                       return_exceptions=True)
        self._cameras.clear()
        self._keys.clear()
        self._reserved_ids.clear()
        if any(isinstance(r, BaseException) for r in results):
            raise TransportError("one or more camera workers failed to close")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()
