"""Constants for the BSK NOTUS integration."""

from datetime import timedelta
import logging
from typing import Final

DOMAIN: Final = "bsk_notus"
LOGGER = logging.getLogger(__package__)

API_BASE_URL: Final = "https://connect.bskhvac.com.tr"
LOGIN_PATH: Final = "/auth/sign-in"
DEVICE_USER_PATH: Final = "/device-user"

SUPPORTED_DEVICE_TYPE: Final = "IGKLCDV10Device"
SUPPORTED_MODEL_PREFIX: Final = "BSK-IGK-LCD"

SCAN_INTERVAL: Final = timedelta(seconds=60)
