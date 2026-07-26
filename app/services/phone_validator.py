import re

from fastapi import HTTPException, status

from app.services.phone_whitelist import canonical_whitelist_phone, is_whitelisted_phone

# Saudi mobile national: 05 + 8 digits (10 total)
_SAUDI_PHONE_05_RE = re.compile(r"^05\d{8}$")
# International: +9665XXXXXXXX or 9665XXXXXXXX
_SAUDI_PHONE_PLUS966_RE = re.compile(r"^\+9665\d{8}$")
_SAUDI_PHONE_966_RE = re.compile(r"^9665\d{8}$")

# Local part after stripping country code: 9 digits starting with 5
_SAUDI_MOBILE_LOCAL_RE = re.compile(r"^5\d{8}$")


def _clean_phone(phone: str) -> str:
    return phone.strip().replace(" ", "").replace("-", "")


def _is_valid_input_format(phone: str) -> bool:
    raw = _clean_phone(phone)
    return bool(
        _SAUDI_PHONE_05_RE.match(raw)
        or _SAUDI_PHONE_PLUS966_RE.match(raw)
        or _SAUDI_PHONE_966_RE.match(raw)
    )


def _extract_local(phone: str) -> str:
    """Strip country code and leading zero; return raw 9-digit local number."""
    raw = _clean_phone(phone)

    if raw.startswith("+966"):
        raw = raw[4:]
    elif raw.startswith("966") and len(raw) == 12:
        raw = raw[3:]
    elif raw.startswith("0"):
        raw = raw[1:]

    return raw


def validate_saudi_phone(phone: str) -> tuple[str, str]:
    """
    Validate and normalise a Saudi mobile phone number.

    Returns:
        (phone_e164, phone_national) e.g. ("+966512345678", "0512345678")

    Raises:
        HTTPException 422 if the number is invalid.
    """
    if is_whitelisted_phone(phone):
        canonical = canonical_whitelist_phone(phone)
        if canonical:
            return canonical

    if not _is_valid_input_format(phone):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "field": "phone",
                "message": (
                    "رقم الجوال يجب أن يكون 10 أرقام ويبدأ بـ 05 أو +966 "
                    "(مثال: 0512345678)"
                ),
            },
        )

    local = _extract_local(phone)

    if not _SAUDI_MOBILE_LOCAL_RE.match(local):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "field": "phone",
                "message": (
                    "رقم الجوال يجب أن يكون 10 أرقام ويبدأ بـ 05 أو +966 "
                    "(مثال: 0512345678)"
                ),
            },
        )

    phone_e164 = f"+966{local}"
    phone_national = f"0{local}"
    return phone_e164, phone_national
