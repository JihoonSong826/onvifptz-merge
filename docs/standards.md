# Standards and Implementation Rationale

[README](../README.md) | [Documentation index](index.md)

References checked November 4, 2026. These are implementation sources, not an ONVIF certification claim.

| Official source | Application |
| --- | --- |
| [Operation Index 2.0](https://www.onvif.org/onvif/ver20/util/operationIndex.html) | User-supplied operation list; cross-checked with WSDL because the index is older |
| [PTZ Service Specification](https://www.onvif.org/specs/srv/ptz/ONVIF-PTZ-Service-Spec.pdf), 26.06 | Sections 5.1 nodes, 5.2 configuration/options, 5.3 movement/Stop, 5.4 presets |
| [PTZ WSDL](https://www.onvif.org/ver20/ptz/wsdl/ptz.wsdl) | XML namespaces, exact field names/order, SOAP actions |
| [Media2 Specification](https://www.onvif.org/specs/srv/media/ONVIF-Media2-Service-Spec.pdf), 26.06 | Section 5.1.2: GetProfiles Type=All includes configurations |
| [Media2 WSDL](https://www.onvif.org/ver20/media/wsdl/media.wsdl) | Configurations/PTZ and VideoSource structure |
| [Device WSDL](https://www.onvif.org/ver10/device/wsdl/devicemgmt.wsdl) | GetSystemDateAndTime, GetServices, GetCapabilities |
| [Media WSDL](https://www.onvif.org/ver10/media/wsdl/media.wsdl) | Media1 GetProfiles and PTZConfiguration |

The supplied Application Programmer's Guide 1.0 (2011), pages 16-19, 35-43, and 72-79, and Media Service Specification 24.12 profile concepts also informed the design. Blocking Sleep examples were not copied; actors use monotonic time and asyncio events.

SHA-256 of WSDL copies inspected during implementation:

```text
ptz.wsdl
6cbeaf5c8d123401d4fe1a5b99bead9b31730fcf113078fa85776c3aefae4d2b
media2.wsdl
0a1d59636910074ec4fb80b9a43f398ce208f4e38a6c7dff414eb6ddba3a1613
```

## XML interoperability details

GetConfiguration uses `PTZConfigurationToken`; GetConfigurationOptions uses `ConfigurationToken`; movement uses `ProfileToken`; node queries use `NodeToken`. Generic names in prose must not replace actual WSDL fields. Omitting both optional `PanTilt` and `Zoom` fields from Stop means stopping all axes.

## Python and licensing

- [quatanium/python-onvif](https://github.com/quatanium/python-onvif) identifies MIT licensing. Its [setup.py](https://github.com/quatanium/python-onvif/blob/master/setup.py) targets Python 2.6/2.7 and depends on suds and suds-passworddigest. It informed example structure but is not a dependency; source was not copied.
- [Python asyncio](https://docs.python.org/3/library/asyncio-task.html): coroutine cancellation differs from terminating synchronous I/O workers. This implementation processes movement outcomes and attempts Stop after cancellation.
- [urllib.request](https://docs.python.org/3/library/urllib.request.html) supplies HTTP Digest and HTTPS transport. Timeouts are not hard real-time guarantees.
- [MIT](https://opensource.org/license/mit) applies to this code; retain the license notice on redistribution.

No external runtime source code or WSDL originals are bundled. Third-party license/notice texts are included separately. No video/codec libraries are included. Review exact dependency versions' LICENSE/NOTICE and commercial-use conditions when adding libraries.

## Validation boundary

Tests cover SOAP structures, authentication calculations, profiles, coordinate limits, isolation, and Stop ordering. Full WSDL/XSD validation and the official ONVIF Conformance Test Tool were not run. Physical direction, timeout adherence, vendor behavior, network-loss stopping, and TLS deployment need hardware validation.

## 0.2.0 reference and dependency update

The [python-onvif-zeep zeep branch](https://github.com/FalkTannhaeuser/python-onvif-zeep/tree/zeep) informed the typed-request and service-adapter design. Source was not copied. Zeep is now an optional direct dependency. See [setup](zeep.md), [licensing](licensing.md), and the schema manifest produced by the preparation tool for the exact resources used. The historical hashes above describe the earlier verification copies, not every future downloaded bundle.
