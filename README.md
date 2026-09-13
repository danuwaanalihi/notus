# BSK NOTUS Home Assistant integration

Unofficial Home Assistant integration for BSK NOTUS heat-recovery ventilation units connected through the BSK Connect cloud.

> [!IMPORTANT]
> This project uses an undocumented BSK Connect API and is not affiliated with or supported by BSK. The cloud API may change without notice.

## Status

Version **0.1.0** is intentionally **read-only**.

It authenticates against BSK Connect, discovers supported NOTUS units, and exposes their current state in Home Assistant. It does **not** call any device-control endpoint and cannot change fan speed, operating mode, temperature, humidity, boost, heater, free-cooling, or any other setting.

Write support is deliberately deferred until the correct NOTUS write endpoint and payload have been captured and verified on real hardware. The Zephyr write path is not compatible with NOTUS and is not used by this integration.

## Supported device

Verified model:

- Device type: `IGKLCDV10Device`
- Device model: `BSK-IGK-LCD-V1.0`
- Device user type observed in BSK Connect: `IGKLCDV10DeviceUser`

Discovery accepts a BSK Connect device when either:

- `__t == "IGKLCDV10Device"`, or
- `deviceModel` starts with `BSK-IGK-LCD`.

Each discovered NOTUS is represented as one Home Assistant device. The stable identifier preference is `deviceID`, then `mbDeviceId`, then `_id`.

## Entities

### Sensors

- Return temperature
- Return humidity
- External temperature
- External humidity
- Supply temperature
- Supply humidity
- Exhaust temperature
- Exhaust humidity
- Supply fan speed
- Extract fan speed
- Supply fan RPM
- Extract fan RPM
- Target temperature
- Target humidity
- Wi-Fi RSSI
- Return CO2
- Operation mode
- Firmware
- Mainboard firmware

`setTemperature` is reported by the verified NOTUS API in tenths of a degree, so for example `210` is exposed as `21.0 °C`.

`retCo2Ppm == -1` is treated as unavailable rather than being exposed as `-1 ppm`.

### Binary sensors

- Power
- Filter warning
- Low fan speed warning
- Manual boost
- Humidity boost
- External boost
- Free cooling
- Preheater attached
- Preheater status

## BSK Connect access

The integration uses only these cloud operations:

- `POST https://connect.bskhvac.com.tr/auth/sign-in` to obtain an access token
- `GET https://connect.bskhvac.com.tr/device-user` to read device data

Device polling is approximately every 60 seconds. If the device-list request returns HTTP 401, the integration performs one fresh login and retries the read once.

No BSK device write endpoint exists in the v0.1.0 code path.

## Installation with HACS

1. Open HACS in Home Assistant.
2. Open **Integrations**.
3. Use the menu and choose **Custom repositories**.
4. Add `https://github.com/danuwaanalihi/notus` as repository type **Integration**.
5. Find **BSK NOTUS** and download it.
6. Restart Home Assistant.
7. Go to **Settings → Devices & services → Add integration**.
8. Search for **BSK NOTUS**.
9. Enter the same email/username and password used by BSK Connect.

The setup flow validates both authentication and the presence of at least one supported NOTUS device before creating the config entry.

## Authentication and errors

The config flow distinguishes:

- invalid authentication
- inability to connect to BSK Connect
- valid account with no supported NOTUS device
- unexpected API/setup errors

Credentials are handled by the Home Assistant config entry and are not written to this repository.

## Design notes

This integration intentionally contains a small dedicated BSK Connect client instead of depending on `bskzephyr`. The existing Zephyr client expects fields such as `fanSpeed` and `groupID`; the verified NOTUS payload instead exposes separate ventilator/aspirator fan fields and does not provide the Zephyr `groupID` expected by that library.

## License

GPL-3.0. See `LICENSE`.
