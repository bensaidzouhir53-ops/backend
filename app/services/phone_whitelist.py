import re

from app.config import get_settings

settings = get_settings()


def _digits_only(phone: str) -> str:
    return re.sub(r"\D", "", phone)


def _whitelist_entries() -> list[str]:
    raw = settings.ORDER_PHONE_WHITELIST or ""
    return [_digits_only(entry) for entry in raw.split(",") if entry.strip()]


def is_whitelisted_phone(phone: str) -> bool:
    """True when the phone matches a configured test whitelist entry."""
    phone_digits = _digits_only(phone)
    if not phone_digits:
        return False

    normalized_variants = {phone_digits, phone_digits.lstrip("0")}
    if phone_digits.startswith("966"):
        normalized_variants.add(phone_digits[3:])
        normalized_variants.add(phone_digits[3:].lstrip("0"))

    for entry in _whitelist_entries():
        if not entry:
            continue
        entry_variants = {entry, entry.lstrip("0")}
        if normalized_variants & entry_variants:
            return True

    return False


def canonical_whitelist_phone(phone: str) -> tuple[str, str] | None:
    """
    Return (e164, national) for a whitelisted phone.
    Pads short test numbers to a valid Saudi mobile shape when needed.
    """
    if not is_whitelisted_phone(phone):
        return None

    digits = _digits_only(phone)

    if digits.startswith("966"):
        local = digits[3:]
    else:
        local = digits.lstrip("0")

    # User test number 055000000 → local 55000000 (8 digits) → pad to 550000000
    if len(local) == 8 and local.startswith("5"):
        local = f"{local}0"

    if len(local) == 9 and local.startswith("5"):
        phone_e164 = f"+966{local}"
        phone_national = f"0{local}"
        return phone_e164, phone_national

    return None
