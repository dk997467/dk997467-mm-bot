import re
from typing import List


# Default regex patterns (strings) for scanning/redaction.
# - PEM private keys block
PEM_PRIVATE_BLOCK = r"-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?-----END [^-]*PRIVATE KEY-----"
# - Generic long hex tokens (>=20)
LONG_HEX_TOKEN = r"(?<![A-Fa-f0-9])[A-Fa-f0-9]{20,}(?![A-Fa-f0-9])"
# - Generic base64-like tokens (>=20, allow /=+_-)
BASE64ISH_TOKEN = r"(?<![A-Za-z0-9/+_=\-])[A-Za-z0-9/+_=\-]{20,}(?![A-Za-z0-9/+_=\-])"
# - AWS Access Key ID
AWS_ACCESS_KEY_ID = r"AKIA[0-9A-Z]{16}"
# - AWS Secret Access Key (40 base64ish chars)
AWS_SECRET_ACCESS_KEY = r"(?<![A-Za-z0-9/+_=\-])[A-Za-z0-9/+]{40}(?![A-Za-z0-9/+])"

# Exported defaults
DEFAULT_PATTERNS: List[str] = [
    PEM_PRIVATE_BLOCK,
    AWS_ACCESS_KEY_ID,
    AWS_SECRET_ACCESS_KEY,
    LONG_HEX_TOKEN,
    BASE64ISH_TOKEN,
]


def redact(text: str, patterns: List[str]) -> str:
    """Redact suspicious secrets in text using provided regex patterns.

    Each match is replaced with '****'. Deterministic result; ASCII preserved.
    """
    redacted = text
    for pat in patterns:
        try:
            rx = re.compile(pat, re.DOTALL)
        except re.error:
            rx = re.compile(pat)
        redacted = rx.sub('****', redacted)

    # Additional key-value masking to catch explicit keys (preserve key and quotes):
    kv = re.compile(r"(?i)(\\b(?:api_key|api-secret|api_secret|password|pg_password|token|secret|aws_secret_access_key)\\s*[:=]\\s*)(\"[^\"]+\"|'[^']+'|[A-Za-z0-9/+_=\-]{6,})")
    def _kv_repl(m: re.Match) -> str:
        prefix = m.group(1)
        val = m.group(2)
        if val.startswith('"') and val.endswith('"'):
            return prefix + '"****"'
        if val.startswith("'") and val.endswith("'"):
            return prefix + "'****'"
        return prefix + '****'
    redacted = kv.sub(_kv_repl, redacted)
    return redacted


