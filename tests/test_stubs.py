import unittest
from ptz_control import stubs


class StubTests(unittest.IsolatedAsyncioTestCase):
    async def test_non_ptz_features_never_claim_connection_success(self):
        results = [await stubs.discover_cameras(),
                   await stubs.open_rtsp_stream("camera"),
                   await stubs.subscribe_events("camera"),
                   await stubs.start_recording("camera"),
                   await stubs.display_stream("camera")]
        self.assertTrue(all(r.status == "not_implemented" for r in results))
        self.assertEqual(results[0].data, [])
