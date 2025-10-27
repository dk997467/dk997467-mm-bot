"""
Secrets Management for MM Bot Live Trading.

Supports multiple backends:
- Memory store (for testing)
- AWS Secrets Manager (for production)

Environment variables:
- SECRETS_BACKEND: memory | aws (default: memory)
- MM_ENV: dev | shadow | soak | prod (default: dev)
- EXCHANGE_ENV: shadow | testnet | live (default: shadow) - determines secret mapping
- AWS_REGION: AWS region for Secrets Manager (default: us-east-1)
- MM_FAKE_SECRETS_JSON: JSON string for in-memory secrets (test only)

Security:
- No secrets are logged or printed in plain text
- Only masked values are shown in debug/error messages
- Strict environment separation
"""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def get_exchange_env() -> str:
    """
    Get EXCHANGE_ENV from environment variable.
    
    Maps to secret environment:
    - shadow: uses dev secrets (no real trading)
    - testnet: uses testnet secrets (testnet trading)
    - live: uses prod secrets (live trading)
    
    Returns:
        Exchange environment: shadow | testnet | live
    """
    exchange_env = os.getenv("EXCHANGE_ENV", "shadow")
    if exchange_env not in ["shadow", "testnet", "live"]:
        logger.warning(
            f"Invalid EXCHANGE_ENV={exchange_env}, defaulting to 'shadow'. "
            "Valid values: shadow, testnet, live"
        )
        return "shadow"
    return exchange_env


def map_exchange_env_to_secret_env(exchange_env: str) -> str:
    """
    Map EXCHANGE_ENV to secret environment.
    
    Args:
        exchange_env: Exchange environment (shadow/testnet/live)
    
    Returns:
        Secret environment (dev/shadow/testnet/prod)
    """
    mapping = {
        "shadow": "dev",        # Shadow mode uses dev secrets
        "testnet": "testnet",   # Testnet mode uses testnet secrets
        "live": "prod",         # Live mode uses prod secrets
    }
    return mapping.get(exchange_env, "dev")


class APICredentials(BaseModel):
    """API credentials for an exchange."""

    api_key: str = Field(..., description="API key")
    api_secret: str = Field(..., description="API secret")
    exchange: str = Field(..., description="Exchange name (bybit/binance/kucoin)")
    env: str = Field(..., description="Environment (dev/shadow/soak/prod)")

    def mask(self) -> dict[str, str]:
        """Return masked credentials for logging."""
        return {
            "api_key": self._mask(self.api_key),
            "api_secret": self._mask(self.api_secret),
            "exchange": self.exchange,
            "env": self.env,
        }

    @staticmethod
    def _mask(value: str) -> str:
        """Mask a secret value, showing only first 3 and last 3 chars."""
        if len(value) <= 6:
            return "***"
        return f"{value[:3]}...***"


class SecretMetadata(BaseModel):
    """Metadata for a secret."""

    key: str
    env: str
    exchange: str
    created_at: str | None = None
    rotation_days: int = 90


class SecretStore(ABC):
    """Abstract interface for secret storage backends."""

    @abstractmethod
    def get_secret_value(self, key: str) -> str:
        """Get a secret value by key."""
        pass

    @abstractmethod
    def put_secret_value(self, key: str, value: str) -> None:
        """Store a secret value."""
        pass

    @abstractmethod
    def list_secrets(self) -> list[str]:
        """List all secret keys."""
        pass

    @abstractmethod
    def delete_secret(self, key: str) -> None:
        """Delete a secret."""
        pass


class InMemorySecretStore(SecretStore):
    """In-memory secret store for testing."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._load_from_env()

    def _load_from_env(self) -> None:
        """Load secrets from MM_FAKE_SECRETS_JSON env var."""
        fake_secrets = os.getenv("MM_FAKE_SECRETS_JSON", "")
        if fake_secrets:
            try:
                data = json.loads(fake_secrets)
                self._store.update(data)
                logger.info(f"Loaded {len(data)} secrets from MM_FAKE_SECRETS_JSON")
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse MM_FAKE_SECRETS_JSON: {e}")

    def get_secret_value(self, key: str) -> str:
        """Get a secret value by key."""
        if key not in self._store:
            raise KeyError(f"Secret not found: {key}")
        return self._store[key]

    def put_secret_value(self, key: str, value: str) -> None:
        """Store a secret value."""
        self._store[key] = value

    def list_secrets(self) -> list[str]:
        """List all secret keys."""
        return sorted(self._store.keys())

    def delete_secret(self, key: str) -> None:
        """Delete a secret."""
        if key in self._store:
            del self._store[key]


class AwsSecretsStore(SecretStore):
    """AWS Secrets Manager backend."""

    def __init__(self, region: str = "us-east-1") -> None:
        self.region = region
        self._client: Any = None

    def _get_client(self) -> Any:
        """Lazy-load boto3 client."""
        if self._client is None:
            try:
                import boto3
                from botocore.config import Config

                config = Config(
                    region_name=self.region,
                    connect_timeout=5,
                    read_timeout=10,
                    retries={"max_attempts": 3, "mode": "standard"},
                )
                self._client = boto3.client("secretsmanager", config=config)
            except ImportError as e:
                raise ImportError(
                    "boto3 is required for AWS Secrets Manager. "
                    "Install with: pip install boto3"
                ) from e
        return self._client

    def get_secret_value(self, key: str) -> str:
        """Get a secret value from AWS Secrets Manager."""
        try:
            client = self._get_client()
            response = client.get_secret_value(SecretId=key)
            return response["SecretString"]
        except Exception as e:
            logger.error(f"Failed to get secret {key}: {e}")
            raise

    def put_secret_value(self, key: str, value: str) -> None:
        """Store a secret value in AWS Secrets Manager."""
        try:
            client = self._get_client()
            try:
                # Try to update existing secret
                client.update_secret(SecretId=key, SecretString=value)
            except client.exceptions.ResourceNotFoundException:
                # Create new secret if it doesn't exist
                client.create_secret(Name=key, SecretString=value)
        except Exception as e:
            logger.error(f"Failed to put secret {key}: {e}")
            raise

    def list_secrets(self) -> list[str]:
        """List all secret keys from AWS Secrets Manager."""
        try:
            client = self._get_client()
            response = client.list_secrets()
            return sorted([s["Name"] for s in response.get("SecretList", [])])
        except Exception as e:
            logger.error(f"Failed to list secrets: {e}")
            raise

    def delete_secret(self, key: str) -> None:
        """Delete a secret from AWS Secrets Manager."""
        try:
            client = self._get_client()
            client.delete_secret(
                SecretId=key, ForceDeleteWithoutRecovery=True
            )
        except Exception as e:
            logger.error(f"Failed to delete secret {key}: {e}")
            raise


class SecretProvider:
    """High-level interface for managing secrets."""

    def __init__(self, store: SecretStore | None = None) -> None:
        """
        Initialize SecretProvider with a storage backend.

        Args:
            store: Storage backend. If None, will be created based on SECRETS_BACKEND env var.
        """
        if store is None:
            backend = os.getenv("SECRETS_BACKEND", "memory")
            if backend == "aws":
                region = os.getenv("AWS_REGION", "us-east-1")
                store = AwsSecretsStore(region=region)
            else:
                store = InMemorySecretStore()
        self._store = store
        self._backend_type = os.getenv("SECRETS_BACKEND", "memory")
    
    def get_backend_info(self) -> dict[str, str]:
        """
        Get backend information for diagnostics.
        
        Returns:
            Dictionary with backend type, exchange_env, and secret_env
        """
        exchange_env = get_exchange_env()
        secret_env = map_exchange_env_to_secret_env(exchange_env)
        return {
            "backend": self._backend_type,
            "exchange_env": exchange_env,
            "secret_env": secret_env,
        }

    def _make_key(self, env: str, exchange: str, key_type: str) -> str:
        """Generate a secret key name."""
        return f"mm-bot/{env}/{exchange}/{key_type}"

    def get_api_key(self, env: str, exchange: str) -> str:
        """Get API key for an exchange in a specific environment."""
        key = self._make_key(env, exchange, "api_key")
        try:
            return self._store.get_secret_value(key)
        except Exception as e:
            logger.error(f"Failed to get API key for {exchange}/{env}: {e}")
            raise

    def get_api_secret(self, env: str, exchange: str) -> str:
        """Get API secret for an exchange in a specific environment."""
        key = self._make_key(env, exchange, "api_secret")
        try:
            return self._store.get_secret_value(key)
        except Exception as e:
            logger.error(f"Failed to get API secret for {exchange}/{env}: {e}")
            raise

    def get_api_credentials(self, env: str, exchange: str) -> APICredentials:
        """Get full API credentials for an exchange."""
        api_key = self.get_api_key(env, exchange)
        api_secret = self.get_api_secret(env, exchange)
        return APICredentials(
            api_key=api_key,
            api_secret=api_secret,
            exchange=exchange,
            env=env,
        )

    def save_credentials(
        self, env: str, exchange: str, api_key: str, api_secret: str
    ) -> None:
        """Save API credentials for an exchange."""
        key_key = self._make_key(env, exchange, "api_key")
        secret_key = self._make_key(env, exchange, "api_secret")

        try:
            self._store.put_secret_value(key_key, api_key)
            self._store.put_secret_value(secret_key, api_secret)
            logger.info(f"Saved credentials for {exchange}/{env}")
        except Exception as e:
            logger.error(f"Failed to save credentials for {exchange}/{env}: {e}")
            raise

    def list_credentials(self) -> list[SecretMetadata]:
        """List all stored credentials."""
        try:
            all_keys = self._store.list_secrets()
            # Filter for mm-bot keys and extract metadata
            credentials: dict[tuple[str, str], SecretMetadata] = {}
            for key in all_keys:
                if not key.startswith("mm-bot/"):
                    continue
                parts = key.split("/")
                if len(parts) >= 4:
                    env = parts[1]
                    exchange = parts[2]
                    key_type = parts[3]
                    cred_key = (env, exchange)
                    if cred_key not in credentials:
                        credentials[cred_key] = SecretMetadata(
                            key=f"mm-bot/{env}/{exchange}",
                            env=env,
                            exchange=exchange,
                        )
            return sorted(credentials.values(), key=lambda x: (x.env, x.exchange))
        except Exception as e:
            logger.error(f"Failed to list credentials: {e}")
            raise

    def rotate_credentials(
        self, env: str, exchange: str, new_api_key: str, new_api_secret: str
    ) -> None:
        """Rotate API credentials (alias for save_credentials)."""
        logger.info(f"Rotating credentials for {exchange}/{env}")
        self.save_credentials(env, exchange, new_api_key, new_api_secret)

    def delete_credentials(self, env: str, exchange: str) -> None:
        """Delete API credentials for an exchange."""
        key_key = self._make_key(env, exchange, "api_key")
        secret_key = self._make_key(env, exchange, "api_secret")

        try:
            self._store.delete_secret(key_key)
            self._store.delete_secret(secret_key)
            logger.info(f"Deleted credentials for {exchange}/{env}")
        except Exception as e:
            logger.error(f"Failed to delete credentials for {exchange}/{env}: {e}")
            raise


# Global singleton for caching (lazy-loaded)
_global_provider: SecretProvider | None = None


def get_secret_provider() -> SecretProvider:
    """Get the global SecretProvider instance."""
    global _global_provider
    if _global_provider is None:
        _global_provider = SecretProvider()
    return _global_provider


@lru_cache(maxsize=32)
def get_api_credentials(env: str, exchange: str) -> APICredentials:
    """
    Get API credentials with caching.

    This is the recommended high-level interface for getting credentials.
    Results are cached to minimize backend calls.
    """
    provider = get_secret_provider()
    return provider.get_api_credentials(env, exchange)


def clear_cache() -> None:
    """Clear the credentials cache."""
    get_api_credentials.cache_clear()
