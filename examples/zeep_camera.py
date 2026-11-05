"""Real-device example with the optional Zeep WSDL request codec.

Same env vars and Stop-on-connect/close behavior as real_camera.py.
Prepare local schemas first. No physical move without --move.
"""
import argparse
import asyncio
import os
from ptz_control import CameraManager, CameraConfig, Credentials
from ptz_control.zeep_transport import zeep_backend_factory


async def main(directory, move):
    config = CameraConfig(
        camera_id="camera-1", device_url=os.environ["ONVIF_DEVICE_URL"],
        credentials=Credentials(os.environ["ONVIF_USERNAME"], os.environ["ONVIF_PASSWORD"]),
        profile_token=os.environ.get("ONVIF_PROFILE_TOKEN"))
    async with CameraManager(backend_factory=zeep_backend_factory(directory)) as manager:
        camera = await manager.add(config)
        print(camera.snapshot())
        if move:
            try:
                print(await camera.move(pan=.1, seconds=.2))
                await asyncio.sleep(.25)
            finally:
                await camera.stop()
        print(await camera.status())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wsdl-dir", default="wsdl_bundle")
    parser.add_argument("--move", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.wsdl_dir, args.move))
