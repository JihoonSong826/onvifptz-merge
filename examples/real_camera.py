"""Explicit real-camera smoke test; never invoked by automated tests.

Set ONVIF_DEVICE_URL, ONVIF_USERNAME and ONVIF_PASSWORD in the environment.
Set ONVIF_PROFILE_TOKEN when more than one PTZ profile exists.
Run python -m examples.real_camera --move to authorize a short physical move.
Without --move it still acquires control and sends Stop on attach/close.
"""
import argparse
import asyncio
import os

from ptz_control import CameraConfig, CameraManager, Credentials


async def main(move=False):
    config = CameraConfig(
        camera_id="camera-1", device_url=os.environ["ONVIF_DEVICE_URL"],
        credentials=Credentials(os.environ["ONVIF_USERNAME"], os.environ["ONVIF_PASSWORD"]),
        profile_token=os.environ.get("ONVIF_PROFILE_TOKEN"),
    )
    async with CameraManager() as manager:
        camera = await manager.add(config)
        print("PTZ binding:", camera.capabilities.binding)
        if move:
            try:
                print(await camera.move(pan=.1, seconds=.2))
                await asyncio.sleep(.25)
            finally:
                await camera.stop()
        print(await camera.status())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--move", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.move))
