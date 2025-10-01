"""
Extended tests for redact() function with new patterns.

Tests email addresses, IP addresses, order IDs, and safe_print() function.
"""
import io
import sys
from src.common.redact import redact, safe_print


def test_redact_email_basic():
    """Test basic email address redaction."""
    text = "Contact us at support@example.com for help"
    result = redact(text)
    assert "support@example.com" not in result
    assert "****" in result
    print(f"[OK] Email redacted: {result}")


def test_redact_email_multiple():
    """Test multiple email addresses."""
    text = "Contact: admin@test.com or support@example.org"
    result = redact(text)
    assert "admin@test.com" not in result
    assert "support@example.org" not in result
    assert result.count("****") >= 2
    print(f"[OK] Multiple emails redacted: {result}")


def test_redact_ip_public():
    """Test public IP address redaction."""
    # Public IPs should be redacted
    text = "Server IP: 203.0.113.42"
    result = redact(text)
    assert "203.0.113.42" not in result
    assert "****" in result
    print(f"[OK] Public IP redacted: {result}")


def test_redact_ip_local_not_redacted():
    """Test that local/private IPs are NOT redacted."""
    # Local IPs should NOT be redacted
    test_cases = [
        "Localhost: 127.0.0.1",
        "Private: 192.168.1.1",
        "Private: 10.0.0.1",
        "Private: 172.16.0.1",
    ]
    
    for text in test_cases:
        result = redact(text)
        # Check that IP is still present (not redacted)
        ip = text.split(": ")[1]
        assert ip in result, f"Local IP {ip} should NOT be redacted"
        print(f"[OK] Local IP preserved: {result}")


def test_redact_order_id_json():
    """Test order ID redaction in JSON-like format."""
    text = '{"orderId":"1234567890abcdef1234"}'
    result = redact(text)
    assert "1234567890abcdef1234" not in result
    assert "****" in result
    print(f"[OK] Order ID redacted: {result}")


def test_redact_api_key_bybit():
    """Test Bybit API key patterns."""
    text = "bybit_api_key=abc123def456789012345"
    result = redact(text)
    assert "abc123def456789012345" not in result
    assert "bybit_api_key=****" in result
    print(f"[OK] Bybit API key redacted: {result}")


def test_redact_api_secret_bybit():
    """Test Bybit API secret patterns."""
    text = "bybit_api_secret: secret123456789012345"
    result = redact(text)
    assert "secret123456789012345" not in result
    assert "****" in result
    print(f"[OK] Bybit API secret redacted: {result}")


def test_safe_print_api_key():
    """Test safe_print() with API key."""
    # Capture stdout
    captured = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured
    
    try:
        # Print with API key (AWS format)
        api_key = "AKIAIOSFODNN7EXAMPLE"
        safe_print(f"API Key: {api_key}")
        
        # Get output
        output = captured.getvalue()
        
        # Check output is redacted
        assert "AKIAIOSFODNN7EXAMPLE" not in output
        assert "****" in output
        print(f"[OK] safe_print redacted API key", file=old_stdout)
    finally:
        # Restore stdout
        sys.stdout = old_stdout


def test_safe_print_multiple_args():
    """Test safe_print() with multiple arguments."""
    # Capture stdout
    captured = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured
    
    try:
        # Print with multiple args containing secrets
        api_key = "abc123def456789012345678901234567890"  # 40 char base64-ish
        password = "my_secret_password_123"
        safe_print("Credentials:", "key=", api_key, "pwd=", password)
        
        # Get output
        output = captured.getvalue()
        
        # Check both secrets are redacted
        assert api_key not in output
        assert password not in output
        assert "****" in output
        print(f"[OK] safe_print redacted multiple secrets", file=old_stdout)
    finally:
        # Restore stdout
        sys.stdout = old_stdout


def test_redact_combined_patterns():
    """Test combined patterns in one string."""
    text = (
        "Server: 203.0.113.42, "
        "Email: admin@example.com, "
        "API: AKIAIOSFODNN7EXAMPLE, "
        "Order: orderId=1234567890abcdef"
    )
    result = redact(text)
    
    # Check all sensitive data is redacted
    assert "203.0.113.42" not in result  # IP
    assert "admin@example.com" not in result  # Email
    assert "AKIAIOSFODNN7EXAMPLE" not in result  # AWS key
    assert "1234567890abcdef" not in result  # Order ID
    
    # Should have multiple ****
    assert result.count("****") >= 4
    print(f"[OK] Combined patterns redacted: {result}")


def test_redact_preserves_structure():
    """Test that redaction preserves text structure."""
    text = "api_key=secret123"
    result = redact(text)
    
    # Should preserve key name
    assert "api_key" in result
    # But redact value
    assert "secret123" not in result
    assert "api_key=****" in result or 'api_key="****"' in result
    print(f"[OK] Structure preserved: {result}")


def test_redact_empty_string():
    """Test redact() with empty string."""
    result = redact("")
    assert result == ""
    print("[OK] Empty string handled correctly")


def test_redact_no_secrets():
    """Test redact() with text containing no secrets."""
    text = "This is a normal log message with no sensitive data."
    result = redact(text)
    assert result == text  # Should be unchanged
    print(f"[OK] No false positives: {result}")


if __name__ == "__main__":
    print("Running extended redact tests...")
    print("=" * 60)
    
    test_redact_email_basic()
    test_redact_email_multiple()
    test_redact_ip_public()
    test_redact_ip_local_not_redacted()
    test_redact_order_id_json()
    test_redact_api_key_bybit()
    test_redact_api_secret_bybit()
    test_safe_print_api_key()
    test_safe_print_multiple_args()
    test_redact_combined_patterns()
    test_redact_preserves_structure()
    test_redact_empty_string()
    test_redact_no_secrets()
    
    print("=" * 60)
    print("[OK] All extended redact tests passed!")

