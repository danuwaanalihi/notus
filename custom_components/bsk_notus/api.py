"""Client for the undocumented BSK Connect API."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import (
    API_BASE_URL,
    DEVICE_USER_PATH,
    LOGIN_PATH,
    SUPPORTED_DEVICE_TYPE,
    SUPPORTED_MODEL_PREFIX,
)
from .controls import CONTROLS

_GOOGLE_SYNC_ERROR_MESSAGE = (
    "Device ID cannot be found. This is usually an indication that the device "
    "may have been removed. Send a Request Sync to re-sync the device in Google."
)


class BSKNotusError(Exception):
    """Base exception for BSK NOTUS API errors."""


class BSKNotusAuthError(BSKNotusError):
    """Authentication with BSK Connect failed."""


class BSKNotusConnectionError(BSKNotusError):
    """The BSK Connect API could not be reached."""


class BSKNotusResponseError(BSKNotusError):
    """The BSK Connect API returned an unexpected response."""


class BSKNotusSyncError(BSKNotusResponseError):
    """Known Google sync failure; only exact read-back can confirm the write."""


@dataclass(frozen=True, slots=True)
class NotusDevice:
    """Normalized snapshot of one NOTUS device."""

    identity: str
    name: str
    model: str | None
    device_type: str | None
    values: dict[str, Any]

    def value(self, key: str) -> Any:
        """Return a raw value from the device snapshot."""
        return self.values.get(key)


class BSKNotusClient:
    """BSK Connect reads plus a restricted, sparse NOTUS write request."""

    def __init__(
        self,
        session: ClientSession,
        username: str,
        password: str,
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._token: str | None = None

    async def async_login(self) -> str:
        """Authenticate and cache the BSK Connect access token."""
        try:
            async with self._session.post(
                f"{API_BASE_URL}{LOGIN_PATH}",
                json={"email": self._username, "password": self._password},
                raise_for_status=False,
            ) as response:
                body = await _safe_json(response)

                if response.status == HTTPStatus.OK:
                    if not isinstance(body, Mapping):
                        raise BSKNotusResponseError(
                            "Login response was not a JSON object"
                        )
                    token = body.get("accessToken")
                    if not isinstance(token, str) or not token:
                        raise BSKNotusResponseError(
                            "Login response did not contain accessToken"
                        )
                    self._token = token
                    return token

                # The existing BSK cloud behavior has been observed to use 403
                # and, for some failed sign-ins, 500 for invalid credentials.
                if response.status in {
                    HTTPStatus.UNAUTHORIZED,
                    HTTPStatus.FORBIDDEN,
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                }:
                    raise BSKNotusAuthError(_message_from_body(body, response.status))

                raise BSKNotusResponseError(
                    f"Login failed with HTTP {response.status}"
                )
        except BSKNotusError:
            raise
        except (ClientError, TimeoutError) as err:
            raise BSKNotusConnectionError(str(err)) from err

    async def async_list_notus_devices(self) -> list[NotusDevice]:
        """Return all supported NOTUS devices visible to the account."""
        payload = await self._async_get_device_users()
        devices: list[NotusDevice] = []

        for item in payload:
            if not isinstance(item, Mapping) or not is_notus_payload(item):
                continue
            devices.append(notus_device_from_payload(item))

        return devices

    async def _async_get_device_users(self) -> list[Any]:
        """Fetch /device-user and refresh the token once after HTTP 401."""
        if self._token is None:
            await self.async_login()

        status, body = await self._async_device_user_request()
        if status == HTTPStatus.UNAUTHORIZED:
            self._token = None
            await self.async_login()
            status, body = await self._async_device_user_request()

        if status == HTTPStatus.UNAUTHORIZED:
            raise BSKNotusAuthError("BSK Connect rejected the refreshed token")
        if status < 200 or status >= 300:
            raise BSKNotusResponseError(
                f"Device list request failed with HTTP {status}"
            )
        if not isinstance(body, list):
            raise BSKNotusResponseError("Device list response was not a JSON list")

        return body

    async def async_write_control(self, device_id: str, key: str, raw: int) -> None:
        """Send exactly one verified field; the coordinator MUST read back.

        Never retry a PUT, including after a timeout: it may already have been
        applied (and retrying boost could restart its timer). The read-back
        path also refreshes an expired token for the next explicit request.
        """
        control = CONTROLS.get(key)
        if (
            not isinstance(device_id, str)
            or not device_id.strip()
            or control is None
            or type(raw) is not int
            or control.raw_value(raw) is None
        ):
            raise BSKNotusResponseError("Invalid NOTUS control request")
        if self._token is None:
            await self.async_login()
        try:
            async with self._session.put(
                f"{API_BASE_URL}/device",
                params={"deviceID": device_id},
                json={key: raw},
                headers={"Authorization": self._token},
                timeout=ClientTimeout(total=20),
                allow_redirects=False,
                raise_for_status=False,
            ) as response:
                # A PUT response is never used as entity state.
                if response.status == HTTPStatus.UNAUTHORIZED:
                    self._token = None
                    raise BSKNotusAuthError("BSK Connect rejected the write token")
                if not 200 <= response.status < 300:
                    body = await _safe_json(response)
                    detail = _write_error_detail(
                        body, (self._token, self._username, self._password, device_id)
                    )
                    error_type = BSKNotusResponseError
                    message = (
                        body.get("message", body.get("error"))
                        if isinstance(body, Mapping) else None
                    )
                    if response.status == HTTPStatus.BAD_REQUEST and (
                        message == _GOOGLE_SYNC_ERROR_MESSAGE
                        or message == [_GOOGLE_SYNC_ERROR_MESSAGE]
                    ):
                        error_type = BSKNotusSyncError
                    raise error_type(
                        f"Control request failed with HTTP {response.status}{detail}"
                    )
        except (ClientError, TimeoutError) as err:
            raise BSKNotusConnectionError(
                "Control request did not complete; its result is uncertain"
            ) from err

    async def _async_device_user_request(self) -> tuple[int, Any]:
        """Perform one read-only device-list request."""
        assert self._token is not None
        try:
            async with self._session.get(
                f"{API_BASE_URL}{DEVICE_USER_PATH}",
                headers={"Authorization": self._token},
                raise_for_status=False,
            ) as response:
                return response.status, await _safe_json(response)
        except (ClientError, TimeoutError) as err:
            raise BSKNotusConnectionError(str(err)) from err


def is_notus_payload(payload: Mapping[str, Any]) -> bool:
    """Return whether a /device-user item matches the verified NOTUS family."""
    values = _device_values(payload)

    device_type = _first_text(values.get("__t"), payload.get("__t"))
    if device_type == SUPPORTED_DEVICE_TYPE:
        return True

    for candidate in (values.get("deviceModel"), payload.get("deviceModel")):
        if isinstance(candidate, str) and candidate.startswith(SUPPORTED_MODEL_PREFIX):
            return True

    return False


def notus_device_from_payload(payload: Mapping[str, Any]) -> NotusDevice:
    """Normalize one supported /device-user item."""
    values = dict(_device_values(payload))

    identity = _first_text(
        values.get("deviceID"),
        values.get("mbDeviceId"),
        values.get("_id"),
        payload.get("_id"),
    )
    if identity is None:
        raise BSKNotusResponseError("NOTUS payload has no stable device identifier")

    model_candidates = (values.get("deviceModel"), payload.get("deviceModel"))
    model = next(
        (
            candidate
            for candidate in model_candidates
            if isinstance(candidate, str)
            and candidate.startswith(SUPPORTED_MODEL_PREFIX)
        ),
        _first_text(*model_candidates),
    )
    device_type = _first_text(values.get("__t"), payload.get("__t"))

    name = _first_text(
        payload.get("title"),
        payload.get("groupTitle"),
        values.get("title"),
        model,
        "BSK NOTUS",
    )
    assert name is not None

    return NotusDevice(
        identity=identity,
        name=name,
        model=model,
        device_type=device_type,
        values=values,
    )


def _device_values(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = payload.get("device")
    if isinstance(nested, Mapping):
        return nested
    return payload


def _first_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


async def _safe_json(response: Any) -> Any:
    try:
        return await response.json(content_type=None)
    except (TypeError, ValueError):
        return None


def _message_from_body(body: Any, status: int) -> str:
    if isinstance(body, Mapping) and body.get("message") is not None:
        return str(body["message"])
    return f"Authentication failed with HTTP {status}"


def _write_error_detail(body: Any, sensitive: tuple[str | None, ...]) -> str:
    """Retain bounded server validation errors without exposing credentials."""
    if not isinstance(body, Mapping):
        return ""
    message = body.get("message", body.get("error"))
    if isinstance(message, list):
        message = "; ".join(item for item in message if isinstance(item, str))
    if not isinstance(message, str):
        return ""
    for value in sorted((v for v in sensitive if v), key=len, reverse=True):
        message = message.replace(value, "[redacted]")
    message = " ".join(message.split())[:512]
    return f": {message}" if message else ""
