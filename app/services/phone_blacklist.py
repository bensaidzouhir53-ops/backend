import re

from app.config import get_settings


def _digits_only(phone: str) -> str:
    return re.sub(r"\D", "", phone)


def _phone_variants(phone: str) -> set[str]:
    phone_digits = _digits_only(phone)
    if not phone_digits:
        return set()

    variants = {phone_digits, phone_digits.lstrip("0")}
    if phone_digits.startswith("966"):
        variants.add(phone_digits[3:])
        variants.add(phone_digits[3:].lstrip("0"))
    return variants


def _blacklist_entries() -> list[str]:
    raw = get_settings().ORDER_PHONE_BLACKLIST or ""
    return [_digits_only(entry) for entry in raw.split(",") if entry.strip()]


def is_blacklisted_phone(phone: str) -> bool:
    """True when the phone matches a configured blacklist entry."""
    normalized_variants = _phone_variants(phone)
    if not normalized_variants:
        return False

    for entry in _blacklist_entries():
        if not entry:
            continue
        entry_variants = {entry, entry.lstrip("0")}
        if normalized_variants & entry_variants:
            return True

    return False
