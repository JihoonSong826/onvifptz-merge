import asyncio
import time
import unittest

from ptz_control import CameraConfig, CameraManager, Credentials
from ptz_control.backend import OnvifBackend
from ptz_control.errors import Busy, ConfigurationError, NotReady, Superseded, TransportError
from ptz_control.simulation import SimulatedTransport


def cfg(name="cam", **kw):
    return CameraConfig(name, f"http://{name}.invalid/device", Credentials("u", "p"), **kw)


async def wait_until(predicate, timeout=1):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(.002)


class ControllerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.wires = {}
        self.options = {}
        def factory(config):
            wire = SimulatedTransport(config, **self.options.get(config.camera_id, {}))
            self.wires[config.camera_id] = wire
            return OnvifBackend(config, wire)
        self.manager = CameraManager(backend_factory=factory)

    async def asyncTearDown(self):
        for wire in self.wires.values():
            wire.fail_stop = False
        await self.manager.close()

    def ops(self, name="cam"):
        return [op for op, _, _ in self.wires[name].calls]

    async def test_watchdog_stops_after_acceptance(self):
        c = await self.manager.add(cfg())
        result = await c.move(pan=.1, seconds=.03)
        self.assertEqual(result.status, "accepted")
        await wait_until(lambda: self.ops().count("Stop") == 2)
        self.assertFalse(self.wires["cam"].moving)

    async def test_slow_camera_does_not_block_other_camera(self):
        self.options["a"] = {"delay": .3}
        a, b = await asyncio.gather(self.manager.add(cfg("a")), self.manager.add(cfg("b")))
        delayed = asyncio.create_task(a.move(pan=.1, seconds=.05))
        await wait_until(self.wires["a"].move_started.is_set)
        start = time.monotonic()
        await b.move(tilt=.1, seconds=.03)
        await b.stop()
        self.assertLess(time.monotonic() - start, .2)
        self.assertFalse(delayed.done())
        await delayed

    async def test_stop_clears_pending_move_and_bypasses_interval(self):
        c = await self.manager.add(cfg(min_interval=1))
        await c.move(pan=.1, seconds=.5)
        pending = asyncio.create_task(c.move(pan=-.1, seconds=.5))
        await asyncio.sleep(.01)
        await c.stop()
        with self.assertRaises(Superseded):
            await pending
        self.assertEqual(self.ops().count("ContinuousMove"), 1)

    async def test_latest_pending_move_wins(self):
        c = await self.manager.add(cfg(min_interval=.06))
        await c.move(pan=.1, seconds=.5)
        old = asyncio.create_task(c.move(pan=.2, seconds=.5))
        await asyncio.sleep(.005)
        new = asyncio.create_task(c.move(pan=.3, seconds=.5))
        with self.assertRaises(Superseded):
            await old
        await new
        self.assertEqual(self.ops().count("ContinuousMove"), 2)

    async def test_new_move_replaces_old_deadline(self):
        c = await self.manager.add(cfg(min_interval=0))
        await c.move(pan=.1, seconds=.06)
        await asyncio.sleep(.02)
        await c.move(pan=.1, seconds=.2)
        await asyncio.sleep(.07)
        self.assertEqual(self.ops().count("Stop"), 1)
        await c.stop()

    async def test_cancelled_inflight_move_stops(self):
        self.options["cam"] = {"delay": .08}
        c = await self.manager.add(cfg())
        moving = asyncio.create_task(c.move(pan=.1, seconds=.5))
        await wait_until(self.wires["cam"].move_started.is_set)
        moving.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await moving
        await wait_until(lambda: self.ops().count("Stop") == 2)
        self.assertFalse(self.wires["cam"].moving)

    async def test_reply_loss_does_not_retry_movement(self):
        self.options["cam"] = {"fail_move": True}
        c = await self.manager.add(cfg())
        with self.assertRaises(TransportError):
            await c.move(pan=.1)
        await wait_until(lambda: self.ops().count("Stop") == 2)
        self.assertEqual(self.ops().count("ContinuousMove"), 1)
        with self.assertRaises(NotReady):
            await c.move(pan=.1)

    async def test_stop_failure_visible_and_recovery_requires_reconnect(self):
        c = await self.manager.add(cfg())
        self.wires["cam"].fail_stop = True
        with self.assertRaises(TransportError):
            await c.stop()
        self.assertEqual(c.state, "faulted")
        self.wires["cam"].fail_stop = False
        await c.stop()
        self.assertEqual(c.state, "faulted")

    async def test_close_while_moving(self):
        c = await self.manager.add(cfg())
        await c.move(pan=.1, seconds=.5)
        await self.manager.remove("cam")
        self.assertEqual(c.state, "closed")
        self.assertFalse(self.wires["cam"].moving)
        with self.assertRaises(NotReady):
            await c.move(pan=.1)

    async def test_duplicate_id_and_capacity(self):
        self.manager.max_cameras = 1
        await self.manager.add(cfg())
        with self.assertRaises(ConfigurationError):
            await self.manager.add(cfg())
        with self.assertRaises(Busy):
            await self.manager.add(cfg("other"))

    async def test_duplicate_physical_ptz_does_not_send_stop(self):
        await self.manager.add(cfg())
        duplicate = CameraConfig("duplicate", "http://cam.invalid/device", Credentials("u", "p"))
        with self.assertRaises(ConfigurationError):
            await self.manager.add(duplicate)
        self.assertNotIn("Stop", self.ops("duplicate"))

    async def test_zero_vector_uses_stop(self):
        c = await self.manager.add(cfg())
        await c.move()
        self.assertEqual(self.ops()[-1], "Stop")

    async def test_close_waits_for_concurrent_add(self):
        adding = asyncio.create_task(self.manager.add(cfg()))
        await asyncio.sleep(0)
        await self.manager.close()
        with self.assertRaises(NotReady):
            await adding
        self.assertTrue(self.wires["cam"].closed)

    async def test_cancelled_add_cleans_up(self):
        adding = asyncio.create_task(self.manager.add(cfg()))
        await asyncio.sleep(0)
        adding.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await adding
        self.assertTrue(self.wires["cam"].closed)
        self.assertEqual(self.manager._reserved_ids, set())

    async def test_numeric_string_duration_is_normalized(self):
        c = await self.manager.add(cfg())
        await asyncio.wait_for(c.move(pan="0.1", seconds="0.03"), 1)
        await wait_until(lambda: self.ops().count("Stop") == 2)

    async def test_failed_final_stop_does_not_prevent_reconnect(self):
        await self.manager.add(cfg())
        self.wires["cam"].fail_stop = True
        with self.assertRaises(TransportError):
            await self.manager.remove("cam")
        fresh = await self.manager.add(cfg())
        self.assertEqual(fresh.state, "ready")

    async def test_overlapping_remove_does_not_erase_new_registration(self):
        old = await self.manager.add(cfg())
        real_close = old.close
        release_old_removal = asyncio.Event()
        calls = 0

        async def delayed_close():
            nonlocal calls
            calls += 1
            this_call = calls
            await real_close()
            if this_call == 2:
                await release_old_removal.wait()

        old.close = delayed_close
        first = asyncio.create_task(self.manager.remove("cam"))
        second = asyncio.create_task(self.manager.remove("cam"))
        try:
            await first
            fresh = await self.manager.add(cfg())
        finally:
            release_old_removal.set()
            await second
        self.assertIs(self.manager.get("cam"), fresh)
        self.assertIn("cam", self.manager._reserved_ids)
        with self.assertRaises(ConfigurationError):
            await self.manager.add(cfg())

    async def test_stop_during_close_is_rejected(self):
        c = await self.manager.add(cfg())
        closing = asyncio.create_task(c.close())
        await wait_until(lambda: c._closing)
        with self.assertRaises(NotReady):
            await c.stop()
        await closing

    async def test_close_does_not_wait_for_lifetime_of_add_caller(self):
        add_finished = asyncio.Event()
        service_exit = asyncio.Event()
        async def service():
            try:
                await self.manager.add(cfg())
            except NotReady:
                pass
            add_finished.set()
            await service_exit.wait()
        service_task = asyncio.create_task(service())
        await asyncio.sleep(0)
        try:
            await asyncio.wait_for(self.manager.close(), 1)
            self.assertTrue(add_finished.is_set())
        finally:
            service_exit.set()
            await service_task
