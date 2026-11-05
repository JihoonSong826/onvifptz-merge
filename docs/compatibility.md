# Camera and NVR Compatibility

[README](../README.md) | [Documentation index](index.md)

All manufacturers below are **untested on hardware**. Brand-wide compatibility is not claimed.

| Manufacturer | Check before connecting | Result |
| --- | --- | --- |
| Hikvision | ONVIF enablement, dedicated account where required, PTZ privileges | Untested |
| Dahua | ONVIF user management, authentication mode, PTZ privileges | Untested |
| Reolink | Model-specific ONVIF/RTSP support, server settings, Hub/NVR routing | Untested |
| TP-Link VIGI/Tapo | Applicable local or Camera Account, supported physical axes | Untested |
| Amcrest | Model-specific ONVIF authentication and local account | Untested |
| ANNKE | ONVIF enablement, user roles, DVR/NVR channel mapping | Untested |

## Direct camera versus NVR

| Item | Direct camera | NVR endpoint |
| --- | --- | --- |
| Device URL | Camera ONVIF address | NVR ONVIF address |
| Credentials | Camera local/dedicated ONVIF account | NVR local/dedicated ONVIF account |
| Target | Camera PTZ profile | Profile mapped to the intended channel |
| Required checks | Camera PTZ privileges/support | Channel privileges and external PTZ exposure |

NVR authentication does not establish PTZ support for every channel. Camera credentials used internally by the NVR are managed on the NVR side. This library authenticates to the configured Device URL and does not guess account names or ports.

## Protocol policy

Use advertised endpoints, profiles, spaces, and ranges rather than brand branches or fixed vendor URLs.

- Media2 is preferred with `Type=All`; `media_version="media1"` forces Media1.
- Fallback is limited to unsupported operations. Authentication failures do not trigger endless account/service retries.
- Separately advertised hosts require `allowed_service_hosts`; addresses are not automatically rewritten for NAT.
- HTTPS certificates are validated. HTTPS-to-HTTP downgrade and HTTP redirects are rejected. Proxy environment variables are not used.
- Implemented scope is SOAP 1.2, UTF-8 XML, UsernameToken, and standard-library HTTP Digest.
- Python 3.11/3.12 HTTP Digest is limited to MD5/SHA-1 families; SHA-256-only devices need a transport extension.
- Vendor field variations, SOAP 1.1, UTF-16 responses, and mandatory extra WS-Addressing behavior are outside the supported guarantee.

## Hardware acceptance checklist

Record model, hardware revision, firmware, direct/NVR route, channel, Media version, profile, NodeToken, space URI, axis ranges, Timeout minimum/maximum, and account type.

1. Select the correct channel profile using read queries. Ambiguous selection must fail.
2. Verify connection-time Stop, then perform a low-speed 0.2-second movement.
3. Check pan/tilt/zoom direction and speed mapping visually or on site.
4. Check Stop, button release, UI shutdown, and process termination.
5. Disconnect networking and verify physical stopping at device Timeout.
6. Confirm lost responses do not replay movement.
7. Measure B's control latency and stream quality while A is delayed.
8. Check wrong passwords, missing privileges, address changes, reboot, and recovery.
9. Prevent duplicate control through multiple profiles or direct/NVR routes to one motor.
10. Test optional position/preset/home movement only after enabling the explicit option and reviewing disconnection behavior.

## Team responsibilities

The connection owner supplies endpoint, credential injection, camera ID, and channel/video/profile mapping. PTZ owns capability queries, movement/Stop, per-device scheduling, and results/errors. The host owns account provisioning, device administration, video, and user control arbitration.

After address/password/profile changes or a fault, remove the old controller and add a new one. Replace UI references and discard stale requests. New connections query capabilities and start with Stop.
