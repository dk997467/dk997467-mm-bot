"""
Secret Store abstraction with dependency injection.

Provides:
- In-memory/env-based fallback for CI/local dev
- AWS Secrets Manager integration with DI
- Easy mocking in unit tests
"""

import json
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from pydantic import BaseModel


class SecretMetadata(BaseModel):
    """Metadata for a secret."""
    source: str  # "env", "aws", "mock"
    path: str


class SecretStore(ABC):
    """Abstract base class for secret stores."""
    
    @abstractmethod
    def get(self, path: str) -> Dict[str, Any]:
        """
        Get secret value as dict.
        
        Args:
            path: Secret identifier (e.g., "mm-bot/prod/bybit-api")
            
        Returns:
            Secret value as dictionary
            
        Raises:
            KeyError: If secret not found
            ValueError: If secret format invalid
        """
        pass
    
    def get_metadata(self, path: str) -> SecretMetadata:
        """Get metadata for a secret (optional, can override)."""
        return SecretMetadata(source="unknown", path=path)


class InMemorySecretStore(SecretStore):
    """
    In-memory secret store for local/CI dev.
    
    Reads from environment variable MM_FAKE_SECRETS_JSON:
    {
        "mm-bot/prod/bybit-api": {"api_key": "test_key", "api_secret": "test_secret"},
        "mm-bot/staging/bybit-api": {"api_key": "staging_key", "api_secret": "staging_secret"}
    }
    """
    
    def __init__(self, env_var: str = "MM_FAKE_SECRETS_JSON"):
        self.env_var = env_var
        self._secrets: Dict[str, Dict[str, Any]] = {}
        self._load_from_env()
    
    def _load_from_env(self):
        """Load secrets from environment variable."""
        raw = os.environ.get(self.env_var, "{}")
        try:
            self._secrets = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in {self.env_var}: {e}")
    
    def get(self, path: str) -> Dict[str, Any]:
        """Get secret from in-memory store."""
        if path not in self._secrets:
            raise KeyError(f"Secret not found: {path} (available: {list(self._secrets.keys())})")
        return self._secrets[path]
    
    def get_metadata(self, path: str) -> SecretMetadata:
        return SecretMetadata(source="env", path=path)


class AwsSecretsStore(SecretStore):
    """
    AWS Secrets Manager store with dependency injection.
    
    Args:
        client: Boto3 secretsmanager client (injected for testability)
    """
    
    def __init__(self, client):
        """
        Initialize with injected boto3 client.
        
        Args:
            client: boto3.client('secretsmanager') instance
        """
        self.client = client
    
    def get(self, path: str) -> Dict[str, Any]:
        """
        Get secret from AWS Secrets Manager.
        
        Args:
            path: SecretId in AWS (e.g., "mm-bot/prod/bybit-api")
            
        Returns:
            Secret value as dictionary
            
        Raises:
            KeyError: If secret not found (ResourceNotFoundException)
            ValueError: If secret format invalid
        """
        try:
            response = self.client.get_secret_value(SecretId=path)
            secret_string = response.get("SecretString")
            
            if not secret_string:
                raise ValueError(f"Secret {path} has no SecretString field")
            
            return json.loads(secret_string)
        
        except json.JSONDecodeError as e:
            raise ValueError(f"Secret {path} contains invalid JSON: {e}")
        except Exception as e:
            # Check for ResourceNotFoundException by name (works with mocked exceptions)
            if "ResourceNotFoundException" in type(e).__name__:
                raise KeyError(f"Secret not found in AWS: {path}")
            # Catch-all for boto3 errors
            raise RuntimeError(f"Failed to get secret {path} from AWS: {e}")
    
    def get_metadata(self, path: str) -> SecretMetadata:
        return SecretMetadata(source="aws", path=path)


def _make_boto3_secrets_client(region: str = "us-east-1", timeout: int = 10):
    """
    Factory for boto3 secretsmanager client.
    
    Separated for easy mocking in tests.
    
    Args:
        region: AWS region
        timeout: Connection timeout in seconds
        
    Returns:
        boto3 secretsmanager client
    """
    import boto3
    from botocore.config import Config
    
    config = Config(
        region_name=region,
        connect_timeout=timeout,
        read_timeout=timeout,
        retries={'max_attempts': 2, 'mode': 'standard'}
    )
    
    return boto3.client('secretsmanager', config=config)


def get_secret_store(mode: Optional[str] = None, region: str = "us-east-1") -> SecretStore:
    """
    Factory for secret stores.
    
    Args:
        mode: Store mode ("aws" or None for in-memory)
              If None, reads from MM_SECRETS_MODE env var
        region: AWS region (for aws mode)
        
    Returns:
        SecretStore instance
        
    Example:
        # Local/CI dev (no AWS):
        store = get_secret_store()  # Uses MM_FAKE_SECRETS_JSON
        
        # Production (AWS):
        store = get_secret_store(mode="aws", region="us-west-2")
        creds = store.get("mm-bot/prod/bybit-api")
    """
    if mode is None:
        mode = os.environ.get("MM_SECRETS_MODE", "").lower()
    
    if mode == "aws":
        client = _make_boto3_secrets_client(region=region)
        return AwsSecretsStore(client=client)
    else:
        # Default: in-memory mode for local/CI
        return InMemorySecretStore()

