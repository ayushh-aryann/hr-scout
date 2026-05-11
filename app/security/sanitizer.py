"""Input sanitization — treats all JD/resume content as untrusted."""

import re
from typing import Any, Dict

import bleach

MAX_JD_LENGTH = 12_000
MAX_RESUME_TEXT_LENGTH = 16_000
MAX_FIELD_LENGTH = 600

# Patterns that suggest prompt injection attempts
_INJECTION_PATTERNS = [
    r"ignore\s+(?:previous|prior|all)\s+instructions",
    r"forget\s+(?:everything|all|your)",
    r"you\s+are\s+now\s+(?:a|an)\s+",
    r"new\s+instructions?\s*:",
    r"<\|im_(?:start|end)\|>",
    r"\[SYSTEM\]",
    r"###\s*(?:SYSTEM|USER|ASSISTANT)\s*###",
    r"</?(?:system|instructions?|prompt)>",
    r"jailbreak",
    r"prompt\s+injection",
    r"disregard\s+(?:the\s+)?(?:above|previous|prior)",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_text(text: str, max_length: int = MAX_FIELD_LENGTH) -> str:
    if not isinstance(text, str):
        return ""
    text = _CONTROL_CHARS_RE.sub("", text)
    # Replace injection patterns — neutralize but preserve the document
    text = _INJECTION_RE.sub("[FILTERED]", text)
    return text[:max_length]


def sanitize_jd(jd_text: str) -> str:
    return sanitize_text(jd_text, MAX_JD_LENGTH)


def sanitize_resume_text(raw_text: str) -> str:
    return sanitize_text(raw_text, MAX_RESUME_TEXT_LENGTH)


def sanitize_string_field(value: str) -> str:
    return sanitize_text(value, MAX_FIELD_LENGTH)


def mask_pii(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of data with PII fields masked — safe for logging."""
    _PII_KEYS = {"email", "phone", "address", "dob", "ssn", "linkedin_url"}
    result: Dict[str, Any] = {}
    for k, v in data.items():
        if k.lower() in _PII_KEYS:
            result[k] = "***MASKED***"
        elif isinstance(v, dict):
            result[k] = mask_pii(v)
        elif isinstance(v, list):
            result[k] = [
                mask_pii(i) if isinstance(i, dict) else i for i in v
            ]
        else:
            result[k] = v
    return result
