# Validation of 0.1.0

The standalone camera-control script was tested successfully by the camera owner before this integration was built. The integration itself has not yet been installed on the Innovo Magic Cube.

## Automated checks

Home Assistant version: **2026.7.4**.

The test run reported **16 passed, 2 subtests passed**:

- Authentication digest construction for SHA-256 and MD5, token rotation, XML escaping, login and logout.
- Flash and stop payloads, duration bounds and login-only validation.
- Rejected credentials and commands are not retried.
- Unsupported protocols and malformed XML are rejected.
- Setup through the actual Home Assistant config-flow manager.
- Registration and invocation of both button entities and the number entity.
- Duration persistence across reload, options updates and unloading.
- Duplicate-address prevention, visible authentication errors, serialization of simultaneous commands and cancellation handling.

No automated test contacts a physical camera or contains real credentials.

## Test-environment limitation

Although all assertions passed, the macOS Python test process exited with a native segmentation fault during final garbage collection. This happened with Python 3.14.3 and 3.14.6. The same shutdown fault was independently reproduced by creating a built-in Home Assistant `tod` config entry in a separate test that did not import WatchAI. A minimal Home Assistant test without a config entry exited normally.

This points to an issue in the local Home Assistant/Python test environment; its root cause has not been established. The test run must not be described as a clean end-to-end pass. The included GitHub workflow provides a Linux check after publication. A real installation and flash/stop check on the Magic Cube remains required.
