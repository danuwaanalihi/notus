# BSK NOTUS Home Assistant integration

Unofficial Home Assistant integration for BSK NOTUS heat-recovery ventilation units connected through the BSK Connect cloud.

> [!IMPORTANT]
> This project uses an undocumented BSK Connect API and is not affiliated with or supported by BSK. The cloud API may change without notice.

## Status

Version **0.2.0** preserves all 28 read-only entities from v0.1.0 and adds six user controls for the verified `BSK-IGK-LCD-V1.0` / `IGKLCDV10Device`.

The NOTUS write endpoint and sparse payload are grounded in the BSK Connect Android client. See [protocol evidence and confirmation behavior](docs/write-protocol.md). All control state comes from cloud read-back. Writes and polling are serialized; parallel changes send separate fields and cannot replay an old full-device snapshot.

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

### Controls

| Entity | Range | Cloud field |
| --- | --- | --- |
| Power switch | Off / On | `deviceStatus` |
| Manual boost switch | Off / On | `manualBoostState` |
| Supply fan speed number | 0–100%, step 1% | `ventilatorFanSpeed` |
| Extract fan speed number | 0–100%, step 1% | `aspiratorFanSpeed` |
| Target temperature number | 15.0–30.0 °C, step 0.1 °C | `setTemperature` (raw tenths) |
| Target humidity number | 0–100%, step 1% | `setHumidity` |

Controls require the verified model/type, a real `deviceID` and a valid existing field. Other readable NOTUS models retain read-only discovery. Existing sensor and binary-sensor identities are unchanged. Free cooling, operation mode, boost speed/time and installer settings remain read-only or unexposed.

The app uses configurable fan presets. Production testing confirmed supply fan 40 → 60 → 40%; a request for 41% instead read back as 60% and was reported as a mismatch. Arbitrary fan percentages and fractional temperature setpoints are not yet confirmed on hardware.

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
- `PUT https://connect.bskhvac.com.tr/device?deviceID=...` with exactly one verified control field

Device polling is approximately every 60 seconds. If the device-list request returns HTTP 401, the integration performs one fresh login and retries the read once.

Each write is preceded by a fresh identity/capability check and followed by cloud read-back, including after an HTTP error or timeout. A failed or mismatched confirmation raises a service error; the integration never fabricates the requested state. An uncertain PUT is not automatically repeated. Read-back can take several seconds while the cloud catches up. A valid cloud value confirms the setting reported by BSK, not an independent measurement of the physical output.

BSK can return one specific HTTP 400 Google Request Sync error after applying a setting. The integration accepts this known response only if fresh read-back confirms the exact requested field and value. Other write errors remain service errors even when read-back succeeds; see the [confirmation contract](docs/write-protocol.md#confirmation-and-concurrency-contract).

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
