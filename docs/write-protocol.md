# NOTUS cloud write evidence (v0.3.0)

## Source and reproducibility

Static inspection of **BSK Connect Android 2.3.2 (27)**, package
`com.bskconnectapp`, published 2026-08-15, retrieved 2026-09-13.
The vendor's [BSK Connect page](https://connect.bskhvac.com.tr/) links the
[official Android listing](https://play.google.com/store/apps/details?id=com.bskconnectapp).
The analyzed package was obtained from the
[APKCombo version download](https://apkcombo.com/bsk-connect/com.bskconnectapp/download/apk/).
This is evidence from the distributed client, not a vendor API specification
or a claim that every control has been tested on hardware.

- XAPK SHA-256: `4f386a413ed90cbd6b446f329f0ed3063aad252b35ed418d74e5a2ad545a5f60`
- `assets/index.android.bundle` SHA-256: `14b4b05a9f8fd724739577e42d98f7d10051905da3e4dd16b90ab49582237965`
- Hermes bytecode version: 96
- Disassembler: [P1sec/hermes-dec](https://github.com/P1sec/hermes-dec/tree/a0f18f97ab661eb8ed659c8c683a0d21ea619e69)

The package and decompiled source are not redistributed in this repository.
The module/function references below refer to that exact bundle.

## Endpoint and identity

Module 535 defines `API_CONFIG.url` as `https://connect.bskhvac.com.tr`.
Module 529's `putRequestWithToken` (function 6157) performs an Axios PUT with
the token directly in `Authorization`, the supplied JSON body and query params.
The device API wrapper (function 10617) passes the path `/device`.

Model routing maps `BSK-IGK-LCD-V1.0` to the `IGKLCDV10` screen. The screen
registration in module 1041 selects module 1636, whose device screen is module
1637 and advanced settings are module 1645. These components call `Device.put`
with query object `{deviceID: device.deviceID}` and a sparse changed-field body.
There is **no Zephyr `groupID`** in this NOTUS write path.

```http
PUT /device?deviceID=<device.deviceID>
Authorization: <accessToken>
Content-Type: application/json

{"setTemperature": 220}
```

Only the real `deviceID` from a fresh device payload may address a write.
Read discovery's `mbDeviceId`/`_id` fallbacks do not authorize control.

## Allowed mappings

| HA control | JSON field | Wire value | Client evidence |
| --- | --- | --- | --- |
| Power | `deviceStatus` | integer 0 or 1 | Device screen, module 1637, function 16552 |
| Manual boost | `manualBoostState` | integer 0 or 1 | Device screen, module 1637, function 16556 |
| Supply fan speed | `ventilatorFanSpeed` | integer percent | Module 1639, function 16594 |
| Extract fan speed | `aspiratorFanSpeed` | integer percent | Module 1638, function 16582 |
| Target temperature | `setTemperature` | integer tenths of °C | Advanced settings module 1645; SelectPrimary module 1647; temperature options module 1648, function 16728 |
| Target humidity | `setHumidity` | integer percent | Advanced settings module 1645; SelectPrimary module 1647 |
| Free cooling mode | `freeCoolingSetting` | 0 Off / 1 On / 2 Auto | Advanced settings function 16649; options function 16730; SelectPrimary function 16700 |
| Five supply preset percentages | `venFanNightSpeed`, `venFanLowSpeed`, `venFanMediumSpeed`, `venFanHighSpeed`, `venFanBoostSpeed` | integer percent in CS mode | Advanced settings function 16649; SelectSecondary functions 16705 / 16712 |
| Five extract preset percentages | Corresponding `aspFan…Speed` fields | integer percent in CS mode | Advanced settings function 16649; SelectSecondary functions 16705 / 16708 |

`SelectPrimary` constructs a body containing its `tag` and selected numeric
value, passes the deviceID query, then refreshes device state. Temperature
option labels divide the numeric wire value by 10. The app's selector offers
16–30 °C in whole degrees; it establishes the wire scaling, not the complete
hardware range. This integration uses the separately confirmed NOTUS Modbus
range 150–300 (15–30 °C). v0.3.0 writes use raw step 10 (1 °C); existing
cloud values still parse with unchanged tenths scaling. Production confirmed
21 → 22 → 21 °C, but a 21.5 °C request remained at 21 °C after 87 seconds.
Fractional writes are therefore rejected before reaching the cloud. Fan and
humidity bounds are 0–100%, from the confirmed device semantics.

The app presents configurable fan presets. For supply, module 1639 (function
16591) reads `venFanNightSpeed`, `venFanLowSpeed`, `venFanMediumSpeed`,
`venFanHighSpeed` and `venFanBoostSpeed`, with defaults 20/40/60/80/100%.
On 2026-09-13, a production supply request of 41% read back as 60%; a subsequent
explicit 40 → 60 → 40% test confirmed both requested values. This does not
establish a general rounding rule or guarantee arbitrary percentage support.
v0.3.0 rejects nonconfigured fan percentages locally (except 0, fan off).
The original number identities remain available alongside named selectors.

### Configurable fan percentages

The IGKLCDV10 Advanced Settings screen (module 1645, function 16649) contains
the **Fan speeds** card. For each of Boost, High, Medium, Low and Night, it
passes the matching `aspFan…Speed` and `venFan…Speed` fields as `tag_1` and
`tag_2` to `SelectSecondary` (module 1647, function 16705). Its two callbacks
(16708 and 16712) pass `{deviceID: device.deviceID}` and a sparse one-tag body
to the same verified `Device.put` wrapper, then refresh.

`FAN_SPEED_OPTIONS` (module 1648, function 16727) produces integers 0–100
labelled percent when `opMode` is `CS`; other modes use different units.
HA percentage writes therefore require fresh `opMode == "CS"`. This does not
add any writable operation-mode mapping.

The five-field tables are read from the actual device payload, without the
app's default fallbacks. A selector resolves the chosen name under the shared
write lock, after fresh preflight, and writes only the resulting fan-speed
field. Preset configuration writes update only their own field. Missing or
invalid tables disable the selector. A percentage matching multiple names
does not establish which name was selected, so the name is reported unknown.

### Free cooling

Advanced Settings passes `freeCoolingSetting` to `SelectPrimary` with
`FREE_COOLING_OPTIONS` (function 16730): Off=0, On=1 and Auto=2, matching the
confirmed Modbus semantics. The app also offers Summer=3; that additional
mode is outside the confirmed device semantics and is not writable here.
The existing `freeCoolingStatus` binary sensor is a separate running-state
field and is never used as the setting or as write confirmation.

No writable operation mode, manual boost speed/duration, heater or installer
settings are exposed. The live operation-mode string is not used to guess a
writable enum.

## Confirmation and concurrency contract

1. Hold one coordinator lock shared with polling for the entire transaction.
2. Read `/device-user` using the existing v0.1.0 read layer. Require the verified
   V1.0 model/type, actual deviceID and a valid existing control field.
3. PUT exactly one allowlisted integer field, with a 20-second request timeout.
   Reject redirects. Never resend an ambiguous write or replay a full snapshot.
4. Always attempt `/device-user` read-back after the PUT, including HTTP failures
   and transport timeouts. For successful PUTs and the known Google sync error,
   read delays are 0, 2, 2, 2, 5, 10, 10, 10, 10, 10, 10 and 10 seconds. The
   entire confirmation phase, including request time, is capped at 90 seconds;
   each control read is also bounded to 20 seconds. Other PUT errors retain the
   previous four-read window and always retain their error status.
5. Publish only data received through the read API. A successful PUT is not a
   confirmed state. Report an error if the requested field does not match.
6. If read-back fails, mark coordinator state unavailable. For a rejected or
   uncertain PUT, publish any valid read-back and retain the write error, with
   one narrowly verified exception: HTTP 400 with the exact Google Request
   Sync message below is accepted only when the same device's requested field
   matches exactly in fresh read-back. Other HTTP errors, authentication
   failures, transport errors and mismatched values still report failure.

The applied supply writes above both returned this HTTP 400 message:

> Device ID cannot be found. This is usually an indication that the device may have been removed. Send a Request Sync to re-sync the device in Google.

This response is classified separately; it is not proof that a write succeeded
or failed. Only the subsequent exact cloud confirmation permits service success.
The exception does not retry the PUT or trigger Google synchronization.

This verifies the cloud-reported setting; it does not independently prove
physical airflow or heating output. Integration unload/shutdown cancellation
releases the lock and invalidates state if confirmation was interrupted.

## Validation

CI executes synthetic API, coordinator and entity tests against Home Assistant
2026.9.2 on Python 3.14. Tests never contact BSK or a real device. Production
deployment and reversible hardware testing are recorded separately in the PR.
