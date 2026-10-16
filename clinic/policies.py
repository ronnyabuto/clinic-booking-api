from datetime import timedelta
from zoneinfo import ZoneInfo

CLINIC_TIMEZONE = ZoneInfo("Africa/Nairobi")
SLOT_DURATION = timedelta(minutes=30)
MIN_NOTICE = timedelta(hours=1)
WHITE_SPACE = (
    "\u0009\u000a\u000b\u000c\u000d\u0020\u0085\u00a0\u1680"
    + "".join(chr(code) for code in range(0x2000, 0x200B))
    + "\u2028\u2029\u202f\u205f\u3000"
)


def normalize_reason(value: str) -> str:
    if "\x00" in value:
        raise ValueError("Cancellation reason must not contain NUL characters")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError("Cancellation reason must contain valid Unicode text") from error
    value = value.strip(WHITE_SPACE)
    if not value:
        raise ValueError("Cancellation reason must contain a non-whitespace character")
    return value
