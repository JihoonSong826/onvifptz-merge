# Optional Zeep Request Codec

[README](../README.md) | [Documentation index](index.md)

## What changed in 0.2.0

The design references the service factory, injectable transport, and typed request
ideas in [python-onvif-zeep's zeep branch](https://github.com/FalkTannhaeuser/python-onvif-zeep/tree/zeep).
Its source code was not copied and `onvif-zeep` is not an installed dependency.
Instead, this project uses Zeep directly through an optional adapter.

```text
CameraController (queue, Stop priority, watchdog, cancellation)
  -> OnvifBackend (profiles, capabilities, ranges, request fields)
     -> ZeepSoapTransport (local WSDL types -> serialized SOAP body)
        -> existing SoapTransport (UsernameToken, HTTP Digest, bounded HTTP(S))
```

The original standard-library transport remains the default. Public movement APIs
and response shapes are unchanged. Selecting Zeep does not add discovery, RTSP,
MQTT, control ownership, or automatic reconnection.

## Installation

From the extracted repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-zeep.lock
.\.venv\Scripts\python.exe -m pip install -e ".[zeep]"
```

The lock file records the exact versions tested on Windows/Python 3.12.14. It is a
version snapshot, not a hash-verified cross-platform wheel lock. Review available
wheels and run tests separately on Jetson/Linux. To resolve versions within the
declared range instead, install `.[zeep]` without the lock file; regenerate the
license inventory if the resolved versions change.

The base installation still has no third-party runtime dependency. Attempting to
use the optional codec without Zeep gives an actionable `ConfigurationError`.

## Prepare official schemas explicitly

```powershell
.\.venv\Scripts\python.exe tools/prepare_wsdl.py --output wsdl_bundle
```

This build-time step downloads Device, Media1, Media2, and PTZ WSDLs plus their
referenced schemas from allowlisted ONVIF, W3C, and OASIS hosts over HTTPS. It uses
no camera credentials. The resulting manifest records each document's logical
URI, local file, and SHA-256. Keep the generated bundle unchanged as a deployment
artifact; repeated downloads may retrieve newer upstream schemas.

Runtime loading is local-only. Every file's hash and path containment are checked.
Imports missing from the manifest fail instead of accessing the network. HTTPS
aliases for HTTP import identifiers refer to the bytes fetched over HTTPS.
The manifest is an integrity snapshot, not a signature: protect it and the bundle
as trusted deployment inputs.

Official schema originals are not included in this source ZIP. They retain their
own copyright/license notices and are not covered by the project's MIT license.
The deployment must include its prepared bundle when using Zeep. See [licenses](licensing.md).

## Enable in an application

```python
from ptz_control import CameraManager
from ptz_control.zeep_transport import zeep_backend_factory

async def connect(config):
    async with CameraManager(
        backend_factory=zeep_backend_factory("wsdl_bundle")
    ) as manager:
        camera = await manager.add(config)
        print(camera.snapshot())
        print(await camera.status())
```

`add()` and context exit send Stop, even in this read-oriented example.
Coordinate control ownership before activating the controller.

With the environment variables described in [integration](integration.md):

```powershell
.\.venv\Scripts\python.exe -m examples.zeep_camera --wsdl-dir wsdl_bundle
```

Only add `--move` when a short physical movement is intended.

## Boundaries and retained safeguards

Zeep parses the constructed operation into WSDL types and renders its request body.
The existing transport adds authentication and sends it. Zeep's own HTTP session
does not contact cameras. Missing required fields and unexpected request elements
are tested; this is not a general-purpose complete XSD facet validator.

Responses still use the existing checked ElementTree parser. Full response-schema
validation, WS-Addressing, and arbitrary WSDL operations are not added. WSDL-based
serialization is not official ONVIF profile conformance.

The adapter retains redirect/proxy restrictions, TLS verification, HTTP Digest,
fresh UsernameToken nonces, clock correction, response-size limits, and the connected
socket deadline. There is no automatic movement retry. Schema loading occurs on
the per-camera worker; response_deadline bounds connected I/O, not schema loading
or the entire add operation.

Zeep uses strict parsing with DTD/entities forbidden and huge-tree mode disabled.
Its `forbid_external` switch is false because Zeep treats WSDL imports as external;
the custom catalog loader, rather than a network loader, enforces import access.

Deliberately excluded upstream patterns: first-profile selection, per-request
daemon threads, global mutable movement state, global proxy-environment changes,
automatic event subscription, and unconditional address replacement.

The [validation manifest](wsdl-validation-manifest.json) records the 14 official documents used for this release test. It is audit evidence, not a runtime bundle; prepare or supply the actual matching files for deployment.
