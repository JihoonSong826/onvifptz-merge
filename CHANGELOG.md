# Changelog

## 0.2.0

- Add optional Zeep WSDL-backed request serialization over the existing bounded
  SOAP transport. Standard-library mode remains the default.
- Add explicit local schema preparation, path/hash validation, and offline imports.
- Add CameraConfig.service_urls for explicit M1 service endpoint mappings without
  bypassing host approval or HTTPS downgrade checks.
- Add JSON-ready snapshot(), get_nodes_data(), and get_configuration_data().
  Existing XML-returning methods and movement signatures remain available.
- Prevent an old concurrent remove operation from clearing a newer registration.
- Add dependency version snapshot, third-party license inventory and notice copies,
  English setup/integration documentation, and regression tests.
- No physical-camera, Jetson, MQTT, RTSP, discovery, or control-arbitration validation
  is implied. No official ONVIF conformance claim is made.
