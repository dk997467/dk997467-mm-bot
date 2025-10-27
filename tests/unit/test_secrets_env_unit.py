"""
Unit tests for secrets module with EXCHANGE_ENV support.

Tests cover:
- get_exchange_env() function
- map_exchange_env_to_secret_env() function
- SecretProvider.get_backend_info() method
- Environment variable handling
- Log masking
"""

import os
from unittest import mock

import pytest

from tools.live import secrets


class TestGetExchangeEnv:
    """Tests for get_exchange_env function."""

    def test_default_shadow(self):
        """Default should be 'shadow' when env var not set."""
        with mock.patch.dict(os.environ, {}, clear=True):
            env = secrets.get_exchange_env()
            assert env == "shadow"

    def test_explicit_shadow(self):
        """Should return 'shadow' when explicitly set."""
        with mock.patch.dict(os.environ, {"EXCHANGE_ENV": "shadow"}):
            env = secrets.get_exchange_env()
            assert env == "shadow"

    def test_testnet(self):
        """Should return 'testnet' when set."""
        with mock.patch.dict(os.environ, {"EXCHANGE_ENV": "testnet"}):
            env = secrets.get_exchange_env()
            assert env == "testnet"

    def test_live(self):
        """Should return 'live' when set."""
        with mock.patch.dict(os.environ, {"EXCHANGE_ENV": "live"}):
            env = secrets.get_exchange_env()
            assert env == "live"

    def test_invalid_value_defaults_shadow(self):
        """Invalid value should default to 'shadow' with warning."""
        with mock.patch.dict(os.environ, {"EXCHANGE_ENV": "invalid"}):
            env = secrets.get_exchange_env()
            assert env == "shadow"

    def test_case_sensitive(self):
        """EXCHANGE_ENV should be case-sensitive."""
        with mock.patch.dict(os.environ, {"EXCHANGE_ENV": "SHADOW"}):
            # Uppercase "SHADOW" is invalid, should default to shadow
            env = secrets.get_exchange_env()
            assert env == "shadow"


class TestMapExchangeEnvToSecretEnv:
    """Tests for map_exchange_env_to_secret_env function."""

    def test_shadow_to_dev(self):
        """Shadow mode should map to dev secrets."""
        secret_env = secrets.map_exchange_env_to_secret_env("shadow")
        assert secret_env == "dev"

    def test_testnet_to_testnet(self):
        """Testnet mode should map to testnet secrets."""
        secret_env = secrets.map_exchange_env_to_secret_env("testnet")
        assert secret_env == "testnet"

    def test_live_to_prod(self):
        """Live mode should map to prod secrets."""
        secret_env = secrets.map_exchange_env_to_secret_env("live")
        assert secret_env == "prod"

    def test_unknown_defaults_dev(self):
        """Unknown environment should default to dev."""
        secret_env = secrets.map_exchange_env_to_secret_env("unknown")
        assert secret_env == "dev"


class TestSecretProviderBackendInfo:
    """Tests for SecretProvider.get_backend_info method."""

    def test_backend_info_shadow(self):
        """Should return correct info for shadow mode."""
        with mock.patch.dict(os.environ, {"EXCHANGE_ENV": "shadow", "SECRETS_BACKEND": "memory"}):
            provider = secrets.SecretProvider()
            info = provider.get_backend_info()
            assert info["backend"] == "memory"
            assert info["exchange_env"] == "shadow"
            assert info["secret_env"] == "dev"

    def test_backend_info_testnet(self):
        """Should return correct info for testnet mode."""
        with mock.patch.dict(os.environ, {"EXCHANGE_ENV": "testnet", "SECRETS_BACKEND": "memory"}):
            provider = secrets.SecretProvider()
            info = provider.get_backend_info()
            assert info["backend"] == "memory"
            assert info["exchange_env"] == "testnet"
            assert info["secret_env"] == "testnet"

    def test_backend_info_live(self):
        """Should return correct info for live mode."""
        with mock.patch.dict(os.environ, {"EXCHANGE_ENV": "live", "SECRETS_BACKEND": "memory"}):
            provider = secrets.SecretProvider()
            info = provider.get_backend_info()
            assert info["backend"] == "memory"
            assert info["exchange_env"] == "live"
            assert info["secret_env"] == "prod"

    def test_backend_type_memory(self):
        """Should correctly identify memory backend."""
        with mock.patch.dict(os.environ, {"SECRETS_BACKEND": "memory"}):
            provider = secrets.SecretProvider()
            info = provider.get_backend_info()
            assert info["backend"] == "memory"

    def test_backend_type_default(self):
        """Default backend should be memory."""
        with mock.patch.dict(os.environ, {}, clear=True):
            provider = secrets.SecretProvider()
            info = provider.get_backend_info()
            assert info["backend"] == "memory"


class TestAPICredentialsMasking:
    """Tests for APICredentials masking."""

    def test_mask_api_key(self):
        """API key should be masked in mask() output."""
        creds = secrets.APICredentials(
            api_key="abc123xyz789",
            api_secret="secret123secret",
            exchange="bybit",
            env="dev",
        )
        masked = creds.mask()
        assert masked["api_key"] == "abc...***"
        assert "abc123xyz789" not in str(masked)

    def test_mask_api_secret(self):
        """API secret should be masked in mask() output."""
        creds = secrets.APICredentials(
            api_key="key123",
            api_secret="abc123xyz789",
            exchange="bybit",
            env="dev",
        )
        masked = creds.mask()
        assert masked["api_secret"] == "abc...***"
        assert "abc123xyz789" not in str(masked)

    def test_mask_short_values(self):
        """Short values should be fully masked."""
        creds = secrets.APICredentials(
            api_key="abc",
            api_secret="xyz",
            exchange="bybit",
            env="dev",
        )
        masked = creds.mask()
        assert masked["api_key"] == "***"
        assert masked["api_secret"] == "***"

    def test_exchange_and_env_not_masked(self):
        """Exchange and env should not be masked."""
        creds = secrets.APICredentials(
            api_key="key123",
            api_secret="secret123",
            exchange="bybit",
            env="dev",
        )
        masked = creds.mask()
        assert masked["exchange"] == "bybit"
        assert masked["env"] == "dev"


class TestInMemorySecretStore:
    """Tests for InMemorySecretStore."""

    def test_put_and_get(self):
        """Should store and retrieve secrets."""
        store = secrets.InMemorySecretStore()
        store.put_secret_value("test_key", "test_value")
        assert store.get_secret_value("test_key") == "test_value"

    def test_get_nonexistent_raises(self):
        """Getting nonexistent secret should raise KeyError."""
        store = secrets.InMemorySecretStore()
        with pytest.raises(KeyError, match="Secret not found"):
            store.get_secret_value("nonexistent")

    def test_list_secrets(self):
        """Should list all secret keys."""
        store = secrets.InMemorySecretStore()
        store.put_secret_value("key1", "value1")
        store.put_secret_value("key2", "value2")
        keys = store.list_secrets()
        assert sorted(keys) == ["key1", "key2"]

    def test_delete_secret(self):
        """Should delete secret."""
        store = secrets.InMemorySecretStore()
        store.put_secret_value("test_key", "test_value")
        store.delete_secret("test_key")
        with pytest.raises(KeyError):
            store.get_secret_value("test_key")

    def test_delete_nonexistent_safe(self):
        """Deleting nonexistent secret should be safe."""
        store = secrets.InMemorySecretStore()
        # Should not raise
        store.delete_secret("nonexistent")

    def test_load_from_env(self):
        """Should load secrets from MM_FAKE_SECRETS_JSON."""
        fake_secrets = '{"key1": "value1", "key2": "value2"}'
        with mock.patch.dict(os.environ, {"MM_FAKE_SECRETS_JSON": fake_secrets}):
            store = secrets.InMemorySecretStore()
            assert store.get_secret_value("key1") == "value1"
            assert store.get_secret_value("key2") == "value2"


class TestSecretProviderKeyFormat:
    """Tests for SecretProvider key generation."""

    def test_make_key_format(self):
        """Should generate key in correct format."""
        store = secrets.InMemorySecretStore()
        provider = secrets.SecretProvider(store=store)
        # Access private method for testing
        key = provider._make_key("dev", "bybit", "api_key")
        assert key == "mm-bot/dev/bybit/api_key"

    def test_get_api_key_uses_correct_key(self):
        """get_api_key should use correct key format."""
        store = secrets.InMemorySecretStore()
        store.put_secret_value("mm-bot/dev/bybit/api_key", "test_key")
        provider = secrets.SecretProvider(store=store)
        api_key = provider.get_api_key("dev", "bybit")
        assert api_key == "test_key"

    def test_get_api_secret_uses_correct_key(self):
        """get_api_secret should use correct key format."""
        store = secrets.InMemorySecretStore()
        store.put_secret_value("mm-bot/dev/bybit/api_secret", "test_secret")
        provider = secrets.SecretProvider(store=store)
        api_secret = provider.get_api_secret("dev", "bybit")
        assert api_secret == "test_secret"

    def test_save_credentials_creates_both_keys(self):
        """save_credentials should create both api_key and api_secret."""
        store = secrets.InMemorySecretStore()
        provider = secrets.SecretProvider(store=store)
        provider.save_credentials("dev", "bybit", "test_key", "test_secret")
        
        assert store.get_secret_value("mm-bot/dev/bybit/api_key") == "test_key"
        assert store.get_secret_value("mm-bot/dev/bybit/api_secret") == "test_secret"

    def test_list_credentials_filters_mm_bot(self):
        """list_credentials should only return mm-bot/* keys."""
        store = secrets.InMemorySecretStore()
        store.put_secret_value("mm-bot/dev/bybit/api_key", "test")
        store.put_secret_value("mm-bot/dev/bybit/api_secret", "test")
        store.put_secret_value("other/key", "test")
        
        provider = secrets.SecretProvider(store=store)
        creds = provider.list_credentials()
        
        # Should have one credential (dev/bybit pair)
        assert len(creds) == 1
        assert creds[0].env == "dev"
        assert creds[0].exchange == "bybit"


class TestIntegrationScenarios:
    """Integration tests for realistic scenarios."""

    def test_full_credential_lifecycle(self):
        """Test complete lifecycle: save -> get -> rotate -> delete."""
        store = secrets.InMemorySecretStore()
        provider = secrets.SecretProvider(store=store)
        
        # 1. Save credentials
        provider.save_credentials("dev", "bybit", "key1", "secret1")
        
        # 2. Get credentials
        creds = provider.get_api_credentials("dev", "bybit")
        assert creds.api_key == "key1"
        assert creds.api_secret == "secret1"
        assert creds.exchange == "bybit"
        assert creds.env == "dev"
        
        # 3. Rotate credentials
        provider.rotate_credentials("dev", "bybit", "key2", "secret2")
        creds_new = provider.get_api_credentials("dev", "bybit")
        assert creds_new.api_key == "key2"
        assert creds_new.api_secret == "secret2"
        
        # 4. Delete credentials
        provider.delete_credentials("dev", "bybit")
        with pytest.raises(Exception):
            provider.get_api_credentials("dev", "bybit")

    def test_multi_environment_isolation(self):
        """Test that different environments are isolated."""
        store = secrets.InMemorySecretStore()
        provider = secrets.SecretProvider(store=store)
        
        # Save credentials for different environments
        provider.save_credentials("dev", "bybit", "dev_key", "dev_secret")
        provider.save_credentials("testnet", "bybit", "testnet_key", "testnet_secret")
        provider.save_credentials("prod", "bybit", "prod_key", "prod_secret")
        
        # Verify isolation
        dev_creds = provider.get_api_credentials("dev", "bybit")
        testnet_creds = provider.get_api_credentials("testnet", "bybit")
        prod_creds = provider.get_api_credentials("prod", "bybit")
        
        assert dev_creds.api_key == "dev_key"
        assert testnet_creds.api_key == "testnet_key"
        assert prod_creds.api_key == "prod_key"

    def test_multi_exchange_support(self):
        """Test that different exchanges are supported."""
        store = secrets.InMemorySecretStore()
        provider = secrets.SecretProvider(store=store)
        
        # Save credentials for different exchanges
        provider.save_credentials("dev", "bybit", "bybit_key", "bybit_secret")
        provider.save_credentials("dev", "binance", "binance_key", "binance_secret")
        
        # Verify isolation
        bybit_creds = provider.get_api_credentials("dev", "bybit")
        binance_creds = provider.get_api_credentials("dev", "binance")
        
        assert bybit_creds.api_key == "bybit_key"
        assert binance_creds.api_key == "binance_key"

