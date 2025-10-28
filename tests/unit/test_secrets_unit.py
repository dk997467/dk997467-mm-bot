"""Unit tests for tools/live/secrets.py"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from tools.live.secrets import (
    APICredentials,
    AwsSecretsStore,
    InMemorySecretStore,
    SecretMetadata,
    SecretProvider,
    SecretStore,
    clear_cache,
    get_api_credentials,
)


class TestAPICredentials:
    """Test APICredentials model."""

    def test_mask_long_secret(self) -> None:
        """Test masking of long secrets."""
        creds = APICredentials(
            api_key="abcdefghijklmnop",
            api_secret="0123456789abcdef",
            exchange="bybit",
            env="dev",
        )
        masked = creds.mask()
        assert masked["api_key"] == "abc...***"
        assert masked["api_secret"] == "012...***"
        assert masked["exchange"] == "bybit"
        assert masked["env"] == "dev"

    def test_mask_short_secret(self) -> None:
        """Test masking of short secrets."""
        creds = APICredentials(
            api_key="abc",
            api_secret="xyz",
            exchange="binance",
            env="prod",
        )
        masked = creds.mask()
        assert masked["api_key"] == "***"
        assert masked["api_secret"] == "***"


class TestInMemorySecretStore:
    """Test InMemorySecretStore."""

    def test_put_and_get(self) -> None:
        """Test storing and retrieving secrets."""
        store = InMemorySecretStore()
        store.put_secret_value("test_key", "test_value")
        assert store.get_secret_value("test_key") == "test_value"

    def test_get_nonexistent_key(self) -> None:
        """Test getting a non-existent key raises KeyError."""
        store = InMemorySecretStore()
        with pytest.raises(KeyError, match="Secret not found: missing"):
            store.get_secret_value("missing")

    def test_list_secrets(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test listing secrets."""
        monkeypatch.delenv("MM_FAKE_SECRETS_JSON", raising=False)
        store = InMemorySecretStore()
        store.put_secret_value("key1", "value1")
        store.put_secret_value("key2", "value2")
        keys = store.list_secrets()
        assert keys == ["key1", "key2"]

    def test_delete_secret(self) -> None:
        """Test deleting a secret."""
        store = InMemorySecretStore()
        store.put_secret_value("key1", "value1")
        store.delete_secret("key1")
        with pytest.raises(KeyError):
            store.get_secret_value("key1")

    def test_delete_nonexistent_key(self) -> None:
        """Test deleting a non-existent key is silent."""
        store = InMemorySecretStore()
        store.delete_secret("missing")  # Should not raise

    def test_load_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test loading secrets from MM_FAKE_SECRETS_JSON."""
        fake_secrets = json.dumps({"key1": "value1", "key2": "value2"})
        monkeypatch.setenv("MM_FAKE_SECRETS_JSON", fake_secrets)
        store = InMemorySecretStore()
        assert store.get_secret_value("key1") == "value1"
        assert store.get_secret_value("key2") == "value2"

    def test_load_from_env_invalid_json(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test handling of invalid JSON in MM_FAKE_SECRETS_JSON."""
        monkeypatch.setenv("MM_FAKE_SECRETS_JSON", "not valid json")
        store = InMemorySecretStore()
        assert "Failed to parse MM_FAKE_SECRETS_JSON" in caplog.text


class TestAwsSecretsStore:
    """Test AwsSecretsStore."""

    def test_get_secret_value(self) -> None:
        """Test getting a secret value from AWS."""
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {"SecretString": "test_value"}

        store = AwsSecretsStore(region="us-east-1")
        store._client = mock_client
        value = store.get_secret_value("test_key")

        assert value == "test_value"
        mock_client.get_secret_value.assert_called_once_with(SecretId="test_key")

    def test_put_secret_value_create(self) -> None:
        """Test creating a new secret in AWS."""
        mock_client = MagicMock()
        mock_client.exceptions.ResourceNotFoundException = type(
            "ResourceNotFoundException", (Exception,), {}
        )
        mock_client.update_secret.side_effect = (
            mock_client.exceptions.ResourceNotFoundException()
        )

        store = AwsSecretsStore(region="us-east-1")
        store._client = mock_client
        store.put_secret_value("test_key", "test_value")

        mock_client.create_secret.assert_called_once_with(
            Name="test_key", SecretString="test_value"
        )

    def test_put_secret_value_update(self) -> None:
        """Test updating an existing secret in AWS."""
        mock_client = MagicMock()

        store = AwsSecretsStore(region="us-east-1")
        store._client = mock_client
        store.put_secret_value("test_key", "test_value")

        mock_client.update_secret.assert_called_once_with(
            SecretId="test_key", SecretString="test_value"
        )

    def test_list_secrets(self) -> None:
        """Test listing secrets from AWS."""
        mock_client = MagicMock()
        mock_client.list_secrets.return_value = {
            "SecretList": [{"Name": "key1"}, {"Name": "key2"}]
        }

        store = AwsSecretsStore(region="us-east-1")
        store._client = mock_client
        keys = store.list_secrets()

        assert keys == ["key1", "key2"]

    def test_delete_secret(self) -> None:
        """Test deleting a secret from AWS."""
        mock_client = MagicMock()

        store = AwsSecretsStore(region="us-east-1")
        store._client = mock_client
        store.delete_secret("test_key")

        mock_client.delete_secret.assert_called_once_with(
            SecretId="test_key", ForceDeleteWithoutRecovery=True
        )

    def test_boto3_not_installed(self) -> None:
        """Test handling of missing boto3."""
        with patch("builtins.__import__", side_effect=ImportError("No boto3")):
            store = AwsSecretsStore(region="us-east-1")
            with pytest.raises(ImportError, match="boto3 is required"):
                store._get_client()

    def test_get_secret_value_error(self) -> None:
        """Test error handling when getting a secret from AWS."""
        mock_client = MagicMock()
        mock_client.get_secret_value.side_effect = Exception("AWS Error")

        store = AwsSecretsStore(region="us-east-1")
        store._client = mock_client

        with pytest.raises(Exception, match="AWS Error"):
            store.get_secret_value("test_key")

    def test_put_secret_value_error(self) -> None:
        """Test error handling when putting a secret to AWS."""
        mock_client = MagicMock()
        # Mock the exceptions attribute to avoid TypeError
        mock_client.exceptions = MagicMock()
        mock_client.exceptions.ResourceNotFoundException = type(
            "ResourceNotFoundException", (Exception,), {}
        )
        mock_client.update_secret.side_effect = Exception("AWS Error")

        store = AwsSecretsStore(region="us-east-1")
        store._client = mock_client

        with pytest.raises(Exception, match="AWS Error"):
            store.put_secret_value("test_key", "test_value")

    def test_list_secrets_error(self) -> None:
        """Test error handling when listing secrets from AWS."""
        mock_client = MagicMock()
        mock_client.list_secrets.side_effect = Exception("AWS Error")

        store = AwsSecretsStore(region="us-east-1")
        store._client = mock_client

        with pytest.raises(Exception, match="AWS Error"):
            store.list_secrets()

    def test_delete_secret_error(self) -> None:
        """Test error handling when deleting a secret from AWS."""
        mock_client = MagicMock()
        mock_client.delete_secret.side_effect = Exception("AWS Error")

        store = AwsSecretsStore(region="us-east-1")
        store._client = mock_client

        with pytest.raises(Exception, match="AWS Error"):
            store.delete_secret("test_key")


class TestSecretProvider:
    """Test SecretProvider."""

    def test_save_and_get_credentials(self) -> None:
        """Test saving and retrieving credentials."""
        store = InMemorySecretStore()
        provider = SecretProvider(store=store)

        provider.save_credentials(
            env="dev",
            exchange="bybit",
            api_key="test_key",
            api_secret="test_secret",
        )

        creds = provider.get_api_credentials(env="dev", exchange="bybit")
        assert creds.api_key == "test_key"
        assert creds.api_secret == "test_secret"
        assert creds.exchange == "bybit"
        assert creds.env == "dev"

    def test_get_api_key(self) -> None:
        """Test getting only API key."""
        store = InMemorySecretStore()
        provider = SecretProvider(store=store)

        provider.save_credentials(
            env="dev",
            exchange="bybit",
            api_key="test_key",
            api_secret="test_secret",
        )

        api_key = provider.get_api_key(env="dev", exchange="bybit")
        assert api_key == "test_key"

    def test_get_api_secret(self) -> None:
        """Test getting only API secret."""
        store = InMemorySecretStore()
        provider = SecretProvider(store=store)

        provider.save_credentials(
            env="dev",
            exchange="bybit",
            api_key="test_key",
            api_secret="test_secret",
        )

        api_secret = provider.get_api_secret(env="dev", exchange="bybit")
        assert api_secret == "test_secret"

    def test_list_credentials(self) -> None:
        """Test listing credentials."""
        store = InMemorySecretStore()
        provider = SecretProvider(store=store)

        provider.save_credentials(
            env="dev", exchange="bybit", api_key="key1", api_secret="secret1"
        )
        provider.save_credentials(
            env="prod", exchange="binance", api_key="key2", api_secret="secret2"
        )

        credentials = provider.list_credentials()
        assert len(credentials) == 2
        assert credentials[0].env == "dev"
        assert credentials[0].exchange == "bybit"
        assert credentials[1].env == "prod"
        assert credentials[1].exchange == "binance"

    def test_rotate_credentials(self) -> None:
        """Test rotating credentials."""
        store = InMemorySecretStore()
        provider = SecretProvider(store=store)

        provider.save_credentials(
            env="dev", exchange="bybit", api_key="old_key", api_secret="old_secret"
        )

        provider.rotate_credentials(
            env="dev", exchange="bybit", new_api_key="new_key", new_api_secret="new_secret"
        )

        creds = provider.get_api_credentials(env="dev", exchange="bybit")
        assert creds.api_key == "new_key"
        assert creds.api_secret == "new_secret"

    def test_delete_credentials(self) -> None:
        """Test deleting credentials."""
        store = InMemorySecretStore()
        provider = SecretProvider(store=store)

        provider.save_credentials(
            env="dev", exchange="bybit", api_key="key", api_secret="secret"
        )

        provider.delete_credentials(env="dev", exchange="bybit")

        with pytest.raises(KeyError):
            provider.get_api_credentials(env="dev", exchange="bybit")

    def test_get_nonexistent_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test getting non-existent credentials raises error."""
        monkeypatch.delenv("MM_FAKE_SECRETS_JSON", raising=False)
        store = InMemorySecretStore()
        provider = SecretProvider(store=store)

        with pytest.raises(Exception):
            provider.get_api_credentials(env="dev", exchange="bybit")

    def test_make_key(self) -> None:
        """Test secret key generation."""
        store = InMemorySecretStore()
        provider = SecretProvider(store=store)

        key = provider._make_key("dev", "bybit", "api_key")
        assert key == "mm-bot/dev/bybit/api_key"

    def test_get_api_key_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test error handling when getting API key."""
        monkeypatch.delenv("MM_FAKE_SECRETS_JSON", raising=False)
        store = InMemorySecretStore()
        provider = SecretProvider(store=store)

        with pytest.raises(Exception):
            provider.get_api_key(env="dev", exchange="bybit")

    def test_get_api_secret_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test error handling when getting API secret."""
        monkeypatch.delenv("MM_FAKE_SECRETS_JSON", raising=False)
        store = InMemorySecretStore()
        provider = SecretProvider(store=store)

        with pytest.raises(Exception):
            provider.get_api_secret(env="dev", exchange="bybit")

    def test_save_credentials_error(self) -> None:
        """Test error handling when saving credentials."""
        mock_store = MagicMock(spec=SecretStore)
        mock_store.put_secret_value.side_effect = Exception("Store error")
        provider = SecretProvider(store=mock_store)

        with pytest.raises(Exception, match="Store error"):
            provider.save_credentials(
                env="dev", exchange="bybit", api_key="key", api_secret="secret"
            )

    def test_list_credentials_error(self) -> None:
        """Test error handling when listing credentials."""
        mock_store = MagicMock(spec=SecretStore)
        mock_store.list_secrets.side_effect = Exception("Store error")
        provider = SecretProvider(store=mock_store)

        with pytest.raises(Exception, match="Store error"):
            provider.list_credentials()

    def test_delete_credentials_error(self) -> None:
        """Test error handling when deleting credentials."""
        mock_store = MagicMock(spec=SecretStore)
        mock_store.delete_secret.side_effect = Exception("Store error")
        provider = SecretProvider(store=mock_store)

        with pytest.raises(Exception, match="Store error"):
            provider.delete_credentials(env="dev", exchange="bybit")


class TestCaching:
    """Test caching functionality."""

    def test_get_api_credentials_cached(self) -> None:
        """Test that get_api_credentials uses cache."""
        clear_cache()

        # Setup provider with test data
        fake_secrets = json.dumps({
            "mm-bot/dev/bybit/api_key": "test_key",
            "mm-bot/dev/bybit/api_secret": "test_secret",
        })
        with patch.dict(os.environ, {"MM_FAKE_SECRETS_JSON": fake_secrets}):
            # First call
            creds1 = get_api_credentials(env="dev", exchange="bybit")
            # Second call should return cached value
            creds2 = get_api_credentials(env="dev", exchange="bybit")

        assert creds1 is creds2  # Same object reference
        clear_cache()

    def test_clear_cache(self) -> None:
        """Test clearing the cache."""
        clear_cache()

        fake_secrets = json.dumps({
            "mm-bot/dev/bybit/api_key": "test_key",
            "mm-bot/dev/bybit/api_secret": "test_secret",
        })
        with patch.dict(os.environ, {"MM_FAKE_SECRETS_JSON": fake_secrets}):
            creds1 = get_api_credentials(env="dev", exchange="bybit")
            clear_cache()
            creds2 = get_api_credentials(env="dev", exchange="bybit")

        # Should be different objects after cache clear
        assert creds1.api_key == creds2.api_key
        clear_cache()


class TestSecretProviderBackendSelection:
    """Test backend selection via environment variables."""

    def test_default_backend_is_memory(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that default backend is memory."""
        monkeypatch.delenv("SECRETS_BACKEND", raising=False)
        provider = SecretProvider()
        assert isinstance(provider._store, InMemorySecretStore)

    def test_memory_backend_explicit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test explicit memory backend selection."""
        monkeypatch.setenv("SECRETS_BACKEND", "memory")
        provider = SecretProvider()
        assert isinstance(provider._store, InMemorySecretStore)

    def test_aws_backend_explicit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test explicit AWS backend selection."""
        monkeypatch.setenv("SECRETS_BACKEND", "aws")
        monkeypatch.setenv("AWS_REGION", "us-west-2")

        provider = SecretProvider()
        assert isinstance(provider._store, AwsSecretsStore)
        assert provider._store.region == "us-west-2"
