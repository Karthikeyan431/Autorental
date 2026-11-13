"""Masked identity fields: which they are, how they are stored, and who may see them in full
(D45, D46; N15 to N17).

* The driver's address and date of birth and the date of birth on the licence are encrypted at
  rest with the field cipher (AES-256-GCM, key id stored). The context binds each value to its
  table, column and row; the licence value follows the driver (like the licence number), so an
  owner reopen can copy it to the new attempt.
* The ID document's date or year of birth and gender are masked in responses but stored as
  they are (N15 covers only the address and the two dates of birth).
* Full values are returned only by the reveal endpoint, never in list, detail or KYC responses,
  audit entries, KYC history, logs or error messages.
"""

from datetime import date

from app.core.config import Settings
from app.core.crypto import field_cipher

# The masked fields, by the names the reveal endpoint uses.
DRIVER_FIELDS = ("address", "date_of_birth")
LICENCE_FIELDS = ("licence_number", "licence_date_of_birth")
IDENTITY_FIELDS = ("id_dob_or_yob", "id_gender")
REVEALABLE_FIELDS = DRIVER_FIELDS + LICENCE_FIELDS + IDENTITY_FIELDS


def _context(table_column: str, driver_id: int) -> str:
    return f"{table_column}:{driver_id}"


def encrypt_driver_field(settings: Settings, column: str, driver_id: int, value: str) -> str:
    return field_cipher(settings).encrypt(value, context=_context(f"drivers.{column}", driver_id))


def decrypt_driver_field(settings: Settings, column: str, driver_id: int, stored: str) -> str:
    return field_cipher(settings).decrypt(stored, context=_context(f"drivers.{column}", driver_id))


def encrypt_date(settings: Settings, column: str, driver_id: int, value: date) -> str:
    return encrypt_driver_field(settings, column, driver_id, value.isoformat())


def encrypt_licence_dob(settings: Settings, driver_id: int, value: date) -> str:
    return field_cipher(settings).encrypt(
        value.isoformat(), context=_context("licence_details.date_of_birth", driver_id)
    )


def decrypt_licence_dob(settings: Settings, driver_id: int, stored: str) -> str:
    return field_cipher(settings).decrypt(
        stored, context=_context("licence_details.date_of_birth", driver_id)
    )


def licence_number_context(driver_id: int) -> str:
    return _context("licence_details.licence_number", driver_id)


def decrypt_licence_number(settings: Settings, driver_id: int, stored: str) -> str:
    return field_cipher(settings).decrypt(stored, context=licence_number_context(driver_id))
