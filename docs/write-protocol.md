# NOTUS v0.2.0 cloud write evidence

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

{"setTemperature": 215}
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

`SelectPrimary` constructs a body containing its `tag` and selected numeric
value, passes the deviceID query, then refreshes device state. Temperature
option labels divide the numeric wire value by 10. The app's selector offers
16–30 °C in whole degrees; it establishes the wire scaling, not the complete
hardware range. This integration uses the separately confirmed NOTUS Modbus
range 150–300 (15–30 °C), with a 0.1 °C step. Fan and humidity bounds are
0–100%, also from the confirmed device semantics. Fractional cloud setpoints
and the reversible 21.0 → 21.5 → 21.0 test still require production validation.

No writable operation mode, free cooling, boost speed/duration, heater or
installer settings are exposed in v0.2.0. The live operation-mode string is
not used to guess a writable enum.

## Confirmation and concurrency contract

1. Hold one coordinator lock shared with polling for the entire transaction.
2. Read `/device-user` using the existing v0.1.0 read layer. Require the verified
   V1.0 model/type, actual deviceID and a valid existing control field.
3. PUT exactly one allowlisted integer field, with a 20-second request timeout.
   Reject redirects. Never resend an ambiguous write or replay a full snapshot.
4. Always attempt `/device-user` read-back after the PUT, including HTTP failures
   and transport timeouts. Allow up to four reads, two seconds apart, for cloud
   propagation; each control read is bounded to 20 seconds.
5. Publish only data received through the read API. A successful PUT is not a
   confirmed state. Report an error if the requested field does not match.
6. If read-back fails, mark coordinator state unavailable. If a rejected or
   uncertain PUT is followed by a valid read, publish that actual state and
   still report the write error. Do not hide an uncertain transaction.

This verifies the cloud-reported setting; it does not independently prove
physical airflow or heating output. Integration unload/shutdown cancellation
releases the lock and invalidates state if confirmation was interrupted.

## Validation

CI executes synthetic API, coordinator and entity tests against Home Assistant
2026.9.2 on Python 3.14. Tests never contact BSK or a real device. Production
deployment and reversible hardware testing are recorded separately in the PR.
