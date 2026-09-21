# WatchAI Deterrence

Local red/blue warning-light controls for compatible WatchAI / Sunell cameras in Home Assistant. Configure everything from the Home Assistant interface; no YAML, terminal, MQTT broker or external computer is needed after installation.

## Controls

- **Flash lights** starts the alternating red/blue lights for the selected duration.
- **Stop flashing** stops the manual flashing command.
- **Flash duration** sets 1–1800 seconds for the next flash. The default is 5 seconds and the value survives Home Assistant restarts.

The camera handles the countdown. Changing the duration does not start the lights or change an active flash. These are command buttons, not a sensor reporting the current light state. Camera-triggered alarm rules may operate separately.

## Install through HACS

1. In **HACS → ⋮ → Custom repositories**, add this repository's GitHub URL and select **Integration**.
2. Find **WatchAI Deterrence** in HACS and download it.
3. Restart Home Assistant.
4. Open **Settings → Devices & services → Add integration → WatchAI Deterrence**.
5. Enter a camera name, its local IP address (or hostname), username and password.

Setup tests login only; it does not flash the camera. Home Assistant must be able to reach the camera directly. For HTTPS, a valid trusted certificate is required. The integration does not disable certificate verification.

Open the new device to use its controls or add them to a dashboard. In an automation, choose the **Button: Press** action and select the camera's **Flash lights** or **Stop flashing** entity. To edit the address or credentials, use the integration's **Configure** option and re-enter the password.

HACS needs a public GitHub repository containing this project. A ZIP on your computer cannot be added as a HACS repository. Only the integration code belongs in that repository; camera credentials are entered later in Home Assistant.

## Compatibility and status

- Targets **Home Assistant 2026.7.4 or newer**; other versions are not verified.
- The underlying standalone login and light-control script was confirmed working on a **WatchAI SN-IPV7182HNBC-B2.8-13**, firmware **v5.0.1306.1006.459.0.3.5.1**.
- The Home Assistant package is an initial release. A successful standalone test is not a completed installation test on the Magic Cube.
- Other Sunell-based models may work but are not claimed as supported hardware.
- This integration controls red/blue lights only. It does not configure motion rules, sirens, white lights or video streams.

## How it works

The integration uses the camera's local `/action/WEB_JsonAjax` endpoint: command `11027` for challenge-response login/logout and command `43917` for `RedBlueLedManualCtrState`. It follows token replacements returned by the camera. Each action uses a new login and attempts logout, avoiding stale browser sessions and persistent background polling. Requests for one configured camera are serialized and blocking network operations run outside Home Assistant's event loop.

Credentials stay in Home Assistant's configuration storage. They are not included in log messages or this repository. Authentication failures are not automatically retried. Buttons raise a Home Assistant action error if the camera rejects the request or cannot be reached; because the integration does not poll, the button's availability is not a live connectivity indicator.

## Development

Run protocol tests without Home Assistant:

```sh
python3 -m unittest discover -s tests -p test_api.py -v
```

Home Assistant integration tests use the pinned version in `requirements-test.txt`:

```sh
python3 -m pip install -r requirements-test.txt
python3 -m pytest tests
```

Tests use synthetic credentials and responses. They do not contact physical cameras.
