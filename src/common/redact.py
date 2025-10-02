import re
from typing import List, Optional


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
# - Email addresses
EMAIL_ADDRESS = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
# - IPv4 addresses (but allow common local/test IPs)
# NOTE: Only redact non-local IPs to avoid false positives
IP_ADDRESS = r"(?!127\.0\.0\.)(?!192\.168\.)(?!10\.)(?!172\.(?:1[6-9]|2[0-9]|3[01])\.)(?<!\d)\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?!\d)"
# - Bybit order IDs (UUID-like strings in order context)
# Example: "orderId":"1234567890abcdef"
ORDER_ID = r"(?i)(?:orderId|orderLinkId|order_id|order_link_id)[\"'\s:=]+([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}|[a-f0-9]{16,})"

# Exported defaults
DEFAULT_PATTERNS: List[str] = [
    PEM_PRIVATE_BLOCK,
    AWS_ACCESS_KEY_ID,
    AWS_SECRET_ACCESS_KEY,
    LONG_HEX_TOKEN,
    BASE64ISH_TOKEN,
    EMAIL_ADDRESS,
    IP_ADDRESS,
    ORDER_ID,
]


def redact(text: str, patterns: Optional[List[str]] = None) -> str:
    """
    Redact suspicious secrets in text using provided regex patterns.

    Args:
        text: Text to redact
        patterns: List of regex patterns. If None, uses DEFAULT_PATTERNS.

    Returns:
        Redacted text with secrets replaced by '****'

    Examples:
        >>> redact("api_key=abc123def456")
        "api_key=****"
        >>> redact("Password: secret123")
        "Password: ****"
    """
    if patterns is None:
        patterns = DEFAULT_PATTERNS
    
    redacted = text
    for pat in patterns:
        try:
            rx = re.compile(pat, re.DOTALL)
        except re.error:
            rx = re.compile(pat)
        redacted = rx.sub('****', redacted)

    # Additional key-value masking to catch explicit keys (preserve key and quotes):
    kv = re.compile(r"(?i)(\\b(?:api_key|api-secret|api_secret|password|pg_password|token|secret|aws_secret_access_key|bybit_api_key|bybit_api_secret)\\s*[:=]\\s*)(\"[^\"]+\"|'[^']+'|[A-Za-z0-9/+_=\-]{6,})")
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


def safe_print(*args, **kwargs) -> None:
    """
    Secure replacement for print() that redacts secrets before output.
    
    Usage:
        from src.common.redact import safe_print
        safe_print("API key:", api_key)  # Automatically redacts
    
    Args:
        *args: Arguments to print (same as print())
        **kwargs: Keyword arguments for print() (file, sep, end, etc.)
    """
    # Convert all args to strings and redact
    redacted_args = []
    for arg in args:
        try:
            text = str(arg)
            redacted_args.append(redact(text))
        except Exception:
            # If redaction fails, still print but mark as potentially unsafe
            redacted_args.append('[REDACT_ERROR]')
    
    # Print redacted content
    print(*redacted_args, **kwargs)


