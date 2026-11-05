"""Run: python -m examples.offline_demo. NO real network access."""
import asyncio

from ptz_control import CameraConfig, CameraManager, Credentials
from ptz_control.simulation import simulated_backend
from ptz_control.stubs import open_rtsp_stream


async def main():
    async with CameraManager(backend_factory=simulated_backend) as manager:
        a, b = await asyncio.gather(*[
            manager.add(CameraConfig(f"cam-{i}", f"http://camera-{i}.invalid/device",
                                     Credentials("simulation", "not-a-real-password")))
            for i in (1, 2)
        ])
        results = await asyncio.gather(a.move(pan=.2, seconds=.05),
                                       b.move(tilt=-.2, seconds=.08))
        for result in results:
            print(result)
        await asyncio.sleep(.12)  # yields only this demo coroutine
        print("OFFLINE status:", await a.status(), await b.status())
        print("RTSP placeholder:", await open_rtsp_stream("cam-1"))


if __name__ == "__main__":
    asyncio.run(main())
