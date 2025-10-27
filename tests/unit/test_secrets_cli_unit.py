"""Unit tests for tools/live/secrets_cli.py"""

from __future__ import annotations

import json
from io import StringIO
from unittest.mock import patch

import pytest

from tools.live.secrets import APICredentials, SecretMetadata
from tools.live.secrets_cli import cmd_fetch, cmd_list, cmd_rotate, cmd_save, main


class TestSecretsCLI:
    """Test secrets CLI commands."""

    def test_cmd_save_success(self, capsys: pytest.CaptureFixture) -> None:
        """Test save command success."""
        with patch("tools.live.secrets_cli.get_secret_provider") as mock_provider:
            mock_provider.return_value.save_credentials.return_value = None

            args = type("Args", (), {
                "env": "dev",
                "exchange": "bybit",
                "api_key": "test_key",
                "api_secret": "test_secret",
            })()

            exit_code = cmd_save(args)

        captured = capsys.readouterr()
        assert exit_code == 0
        output = json.loads(captured.out)
        assert output["status"] == "OK"
        assert output["action"] == "save"
        assert output["env"] == "dev"
        assert output["exchange"] == "bybit"

    def test_cmd_save_error(self, capsys: pytest.CaptureFixture) -> None:
        """Test save command error handling."""
        with patch("tools.live.secrets_cli.get_secret_provider") as mock_provider:
            mock_provider.return_value.save_credentials.side_effect = Exception("Save failed")

            args = type("Args", (), {
                "env": "dev",
                "exchange": "bybit",
                "api_key": "test_key",
                "api_secret": "test_secret",
            })()

            exit_code = cmd_save(args)

        captured = capsys.readouterr()
        assert exit_code == 1
        output = json.loads(captured.out)
        assert output["status"] == "ERROR"
        assert "Save failed" in output["error"]

    def test_cmd_fetch_success(self, capsys: pytest.CaptureFixture) -> None:
        """Test fetch command success."""
        with patch("tools.live.secrets_cli.get_secret_provider") as mock_provider:
            mock_creds = APICredentials(
                api_key="test_key_123",
                api_secret="test_secret_456",
                exchange="bybit",
                env="dev",
            )
            mock_provider.return_value.get_api_credentials.return_value = mock_creds

            args = type("Args", (), {
                "env": "dev",
                "exchange": "bybit",
            })()

            exit_code = cmd_fetch(args)

        captured = capsys.readouterr()
        assert exit_code == 0
        output = json.loads(captured.out)
        assert output["status"] == "OK"
        assert output["action"] == "fetch"
        assert output["credentials"]["api_key"] == "tes...***"
        assert output["credentials"]["api_secret"] == "tes...***"

    def test_cmd_fetch_error(self, capsys: pytest.CaptureFixture) -> None:
        """Test fetch command error handling."""
        with patch("tools.live.secrets_cli.get_secret_provider") as mock_provider:
            mock_provider.return_value.get_api_credentials.side_effect = KeyError("Not found")

            args = type("Args", (), {
                "env": "dev",
                "exchange": "bybit",
            })()

            exit_code = cmd_fetch(args)

        captured = capsys.readouterr()
        assert exit_code == 1
        output = json.loads(captured.out)
        assert output["status"] == "ERROR"
        assert "Not found" in output["error"]

    def test_cmd_rotate_success(self, capsys: pytest.CaptureFixture) -> None:
        """Test rotate command success."""
        with patch("tools.live.secrets_cli.get_secret_provider") as mock_provider:
            mock_provider.return_value.rotate_credentials.return_value = None

            args = type("Args", (), {
                "env": "prod",
                "exchange": "binance",
                "new_api_key": "new_key",
                "new_api_secret": "new_secret",
            })()

            exit_code = cmd_rotate(args)

        captured = capsys.readouterr()
        assert exit_code == 0
        output = json.loads(captured.out)
        assert output["status"] == "OK"
        assert output["action"] == "rotate"
        assert output["env"] == "prod"
        assert output["exchange"] == "binance"

    def test_cmd_rotate_error(self, capsys: pytest.CaptureFixture) -> None:
        """Test rotate command error handling."""
        with patch("tools.live.secrets_cli.get_secret_provider") as mock_provider:
            mock_provider.return_value.rotate_credentials.side_effect = Exception("Rotate failed")

            args = type("Args", (), {
                "env": "prod",
                "exchange": "binance",
                "new_api_key": "new_key",
                "new_api_secret": "new_secret",
            })()

            exit_code = cmd_rotate(args)

        captured = capsys.readouterr()
        assert exit_code == 1
        output = json.loads(captured.out)
        assert output["status"] == "ERROR"
        assert "Rotate failed" in output["error"]

    def test_cmd_list_success(self, capsys: pytest.CaptureFixture) -> None:
        """Test list command success."""
        with patch("tools.live.secrets_cli.get_secret_provider") as mock_provider:
            mock_creds = [
                SecretMetadata(
                    key="mm-bot/dev/bybit",
                    env="dev",
                    exchange="bybit",
                    rotation_days=90,
                ),
                SecretMetadata(
                    key="mm-bot/prod/binance",
                    env="prod",
                    exchange="binance",
                    rotation_days=90,
                ),
            ]
            mock_provider.return_value.list_credentials.return_value = mock_creds

            args = type("Args", (), {})()

            exit_code = cmd_list(args)

        captured = capsys.readouterr()
        assert exit_code == 0
        output = json.loads(captured.out)
        assert output["status"] == "OK"
        assert output["action"] == "list"
        assert output["count"] == 2
        assert len(output["credentials"]) == 2
        assert output["credentials"][0]["env"] == "dev"
        assert output["credentials"][1]["env"] == "prod"

    def test_cmd_list_error(self, capsys: pytest.CaptureFixture) -> None:
        """Test list command error handling."""
        with patch("tools.live.secrets_cli.get_secret_provider") as mock_provider:
            mock_provider.return_value.list_credentials.side_effect = Exception("List failed")

            args = type("Args", (), {})()

            exit_code = cmd_list(args)

        captured = capsys.readouterr()
        assert exit_code == 1
        output = json.loads(captured.out)
        assert output["status"] == "ERROR"
        assert "List failed" in output["error"]

    def test_main_save_command(self, capsys: pytest.CaptureFixture) -> None:
        """Test main function with save command."""
        with patch("tools.live.secrets_cli.get_secret_provider") as mock_provider:
            mock_provider.return_value.save_credentials.return_value = None

            exit_code = main([
                "save",
                "--env", "dev",
                "--exchange", "bybit",
                "--api-key", "key",
                "--api-secret", "secret",
            ])

        assert exit_code == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["status"] == "OK"

    def test_main_fetch_command(self, capsys: pytest.CaptureFixture) -> None:
        """Test main function with fetch command."""
        with patch("tools.live.secrets_cli.get_secret_provider") as mock_provider:
            mock_creds = APICredentials(
                api_key="test_key",
                api_secret="test_secret",
                exchange="bybit",
                env="dev",
            )
            mock_provider.return_value.get_api_credentials.return_value = mock_creds

            exit_code = main([
                "fetch",
                "--env", "dev",
                "--exchange", "bybit",
            ])

        assert exit_code == 0

    def test_main_list_command(self, capsys: pytest.CaptureFixture) -> None:
        """Test main function with list command."""
        with patch("tools.live.secrets_cli.get_secret_provider") as mock_provider:
            mock_provider.return_value.list_credentials.return_value = []

            exit_code = main(["list"])

        assert exit_code == 0

    def test_main_rotate_command(self, capsys: pytest.CaptureFixture) -> None:
        """Test main function with rotate command."""
        with patch("tools.live.secrets_cli.get_secret_provider") as mock_provider:
            mock_provider.return_value.rotate_credentials.return_value = None

            exit_code = main([
                "rotate",
                "--env", "prod",
                "--exchange", "binance",
                "--new-api-key", "new_key",
                "--new-api-secret", "new_secret",
            ])

        assert exit_code == 0

