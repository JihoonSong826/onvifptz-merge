# Testing and Validation Limits

[README](../README.md) | [Documentation index](index.md)

## Running checks

From the repository root:

```powershell
python -m unittest discover -v
python -m examples.offline_demo
```

Recorded result: **60 passing tests** on Windows / Python 3.12.14, Zeep 4.3.3, with the prepared official WSDL bundle enabled for version 0.2.0. Tests use synthetic SOAP responses and localhost HTTP servers, not physical cameras. The code targets Python 3.11+, but other operating systems and versions require separate execution checks.

`127.0.0.1` is the computer's loopback address, not a Python virtual-environment address. Tests use temporary local servers; production uses actual device URLs. The offline demo uses no network.

Version 0.2.0 adds a Zeep codec, M1 integration data, endpoint overrides, and a concurrent-remove fix. This is not a hardware validation claim.

With no optional Zeep installation: 49 tests pass and 11 optional tests skip.
With Zeep but no ONVIF_TEST_WSDL_DIR: the official-bundle test skips.
To enable all 60 tests after following [Zeep setup](zeep.md):

```powershell
$env:ONVIF_TEST_WSDL_DIR = (Resolve-Path wsdl_bundle).Path
python -m unittest discover -v
```

The official-bundle test renders implemented Device/Media1/Media2/PTZ requests against downloaded WSDL types using simulated responses. It does not contact a camera or certify the responses.

## Reproduced review defects

| Defect | Fix | Regression evidence |
| --- | --- | --- |
| String seconds could terminate actor | Normalize before queueing; protect actor and settle waiters | String duration movement and Stop complete |
| Final Stop failure blocked re-registration | Release closed registration in finally | Failed remove followed by successful add |
| Shutdown Stop could wait forever | Reject on closing/finished actor with NotReady | No pending Stop caller in shutdown race |
| Manager close waited for caller service lifetime | Track add-completion Future | Close completes while caller remains alive |
| Slow headers exceeded response budget | Connected-socket shutdown watchdog | Header trickling bounded by deadline |

## Additional coverage

Media1/Media2 and Type=All, token/source selection, ambiguity rejection, unsupported axes, nonfinite/out-of-range values, Timeout limits, option gates, UsernameToken digest, HTTP Digest challenge, redirect rejection, response-size limits, camera isolation, movement replacement, Stop priority, cancellation-to-Stop, no movement retry after response loss, and explicit stub results.

## New 0.2.0 coverage

M1 service overrides and endpoint allowlists, immutable configuration mappings,
JSON snapshots without credential fields, repeated XML child preservation, local
schema hashes/path containment, absent import rejection, DTD rejection, typed
request fields, and the existing HTTP authentication/redirect/size/deadline tests
with Zeep enabled. A regression test prevents an old overlapping remove operation
from erasing a newer controller registration.

## Review scope

The initial 0.1 review reproduced the five defects above. A prior follow-up was interrupted by a workspace credit error. For 0.2.0, independent read-only review completed with no new findings after the overlapping-remove fix; the reviewer also ran all 60 tests with the official bundle. Residual validation gaps remain below.

## Remaining validation

Hardware TLS/certificates, full WSDL/XSD conformance, official ONVIF testing, physical directions, device Timeout adherence, NVR forwarding, and model/firmware performance remain unverified. DNS and OS connection setup cannot be forcibly terminated by this worker design. See [safety](safety.md) and the [acceptance checklist](compatibility.md).
