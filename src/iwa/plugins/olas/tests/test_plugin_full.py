"""Integration tests for OlasPlugin."""

from unittest.mock import MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from iwa.plugins.olas.importer import DiscoveredKey, DiscoveredService, ImportResult
from iwa.plugins.olas.plugin import OlasPlugin


@pytest.fixture
def plugin():
    """Mock Olas plugin."""
    return OlasPlugin()


@pytest.fixture
def runner():
    """CLI runner fixture."""
    return CliRunner()


def test_plugin_metadata(plugin):
    """Test plugin metadata methods."""
    assert plugin.name == "olas"
    assert plugin.config_model.__name__ == "OlasConfig"
    assert "create" in plugin.get_cli_commands()
    assert "import" in plugin.get_cli_commands()


def test_get_tui_view(plugin):
    """Test TUI view creation."""
    with patch("iwa.plugins.olas.tui.olas_view.OlasView") as mock_view:
        view = plugin.get_tui_view()
        assert view is not None
        mock_view.assert_called_once()


def test_create_service_cli(plugin, runner):
    """Test create_service CLI command."""
    app = typer.Typer()
    app.command()(plugin.create_service)

    with (
        patch("iwa.plugins.olas.plugin.ServiceManager") as mock_sm_cls,
        patch("iwa.plugins.olas.plugin.Wallet"),
    ):
        mock_sm = mock_sm_cls.return_value
        result = runner.invoke(app, ["--chain", "gnosis", "--bond", "1"])
        assert result.exit_code == 0
        mock_sm.create.assert_called_once()


def test_import_services_cli_scan_only(plugin, runner):
    """Test import_services CLI in dry-run mode."""
    app = typer.Typer()
    app.command()(plugin.import_services)

    with (
        patch("iwa.plugins.olas.importer.OlasServiceImporter") as mock_importer_cls,
        patch.object(OlasPlugin, "_get_safe_signers", return_value=(None, None)),
    ):
        mock_importer = mock_importer_cls.return_value
        mock_importer.scan_directory.return_value = [
            DiscoveredService(service_id=1, service_name="Test", chain_name="gnosis")
        ]

        # Test dry-run
        result = runner.invoke(app, ["/tmp/test", "--dry-run"])
        assert result.exit_code == 0
        assert "Found 1 service(s)" in result.output
        assert "Dry run mode" in result.output


def test_import_services_cli_full(plugin, runner):
    """Test full import_services CLI with confirmation."""
    app = typer.Typer()
    app.command()(plugin.import_services)

    with patch("iwa.plugins.olas.importer.OlasServiceImporter") as mock_importer_cls:
        mock_importer = mock_importer_cls.return_value
        # Mock discovered service with an encrypted key to trigger password prompt
        key = DiscoveredKey(address="0x1", is_encrypted=True, role="agent")
        service = DiscoveredService(
            service_id=1, service_name="Test", chain_name="gnosis", keys=[key]
        )
        mock_importer.scan_directory.return_value = [service]

        # Mock successful import
        mock_importer.import_service.return_value = ImportResult(
            success=True, message="Imported", imported_services=["gnosis:1"]
        )

        # Test with -y and providing password
        result = runner.invoke(app, ["/tmp/test", "-y", "-p", "secret"])
        assert result.exit_code == 0
        assert "Imported services: gnosis:1" in result.output
        assert "Summary" in result.output


def test_get_safe_signers_edge_cases(plugin):
    """Test _get_safe_signers with various failure scenarios."""
    # 1. No RPC configured
    with patch("iwa.core.settings.settings") as mock_settings:
        mock_settings.gnosis_rpc = None
        signers, exists = plugin._get_safe_signers("0x1", "gnosis")
        assert signers is None
        assert exists is None

    # 2. Safe doesn't exist (raises exception)
    with patch("iwa.core.settings.settings") as mock_settings:
        mock_settings.gnosis_rpc = MagicMock()
        with patch("safe_eth.eth.EthereumClient"), patch("safe_eth.safe.Safe") as mock_safe_cls:
            mock_safe = mock_safe_cls.return_value
            mock_safe.retrieve_owners.side_effect = Exception("Generic error")

            signers, exists = plugin._get_safe_signers("0x1", "gnosis")
            assert signers == []
            assert exists is False

    # 3. Success path
    with patch("iwa.core.settings.settings") as mock_settings:
        mock_settings.gnosis_rpc = MagicMock()
        with patch("safe_eth.eth.EthereumClient"), patch("safe_eth.safe.Safe") as mock_safe_cls:
            mock_safe = mock_safe_cls.return_value
            mock_safe.retrieve_owners.return_value = ["0xAgent"]

            signers, exists = plugin._get_safe_signers("0x1", "gnosis")
            assert signers == ["0xAgent"]
            assert exists is True


def test_import_services_cli_abort(plugin, runner):
    """Test import_services CLI aborting on confirmation."""
    app = typer.Typer()
    app.command()(plugin.import_services)

    with patch("iwa.plugins.olas.importer.OlasServiceImporter") as mock_importer_cls:
        mock_importer = mock_importer_cls.return_value
        mock_importer.scan_directory.return_value = [
            DiscoveredService(service_id=1, service_name="Test", chain_name="gnosis")
        ]

        # Simulate 'n' to confirmation prompt
        result = runner.invoke(app, ["/tmp/test"], input="n\n")
        assert result.exit_code == 0
        assert "Aborted" in result.output
        mock_importer.import_service.assert_not_called()


def test_import_services_cli_no_services(plugin, runner):
    """Test import_services CLI when no services are found."""
    app = typer.Typer()
    app.command()(plugin.import_services)

    with patch("iwa.plugins.olas.importer.OlasServiceImporter") as mock_importer_cls:
        mock_importer = mock_importer_cls.return_value
        mock_importer.scan_directory.return_value = []

        result = runner.invoke(app, ["/tmp/test"])
        assert result.exit_code == 0
        assert "No Olas services found" in result.output


def test_import_services_cli_complex_display(plugin, runner):
    """Test import_services CLI display logic with Safe verification and signer check."""
    app = typer.Typer()
    app.command()(plugin.import_services)

    with (
        patch("iwa.plugins.olas.importer.OlasServiceImporter") as mock_importer_cls,
        patch.object(OlasPlugin, "_get_safe_signers") as mock_get_signers,
    ):
        mock_importer = mock_importer_cls.return_value
        # 1. Service with valid Safe and agent is signer
        key = DiscoveredKey(address="0xAgent", role="agent")
        service = DiscoveredService(service_id=1, safe_address="0xSafe", keys=[key])
        mock_importer.scan_directory.return_value = [service]

        # Mock Safe exists with Agent as signer
        mock_get_signers.return_value = (["0xAgent"], True)

        result = runner.invoke(app, ["/tmp/test", "--dry-run"])
        assert "0xSafe" in result.output
        assert "✓" in result.output
        assert "0xAgent 🔓 plaintext" in result.output  # Not a warning

        # 2. Service where agent is NOT a signer
        mock_get_signers.return_value = (["0xOther"], True)
        result = runner.invoke(app, ["/tmp/test", "--dry-run"])
        assert "NOT A SIGNER OF THE SAFE" in result.output


def test_import_services_cli_password_prompt(plugin, runner):
    """Test import_services CLI prompting for password."""
    app = typer.Typer()
    app.command()(plugin.import_services)

    with patch("iwa.plugins.olas.importer.OlasServiceImporter") as mock_importer_cls:
        mock_importer = mock_importer_cls.return_value
        key = DiscoveredKey(address="0x1", is_encrypted=True, role="agent")
        service = DiscoveredService(service_id=1, keys=[key])
        mock_importer.scan_directory.return_value = [service]
        mock_importer.import_service.return_value = ImportResult(success=True, message="OK")

        # input="y\nsecret\n" -> 'y' for confirm import, 'secret' for password prompt
        result = runner.invoke(app, ["/tmp/test"], input="y\nsecret\n")
        assert result.exit_code == 0
        assert "password" in result.output.lower()
        mock_importer.import_service.assert_called_with(service, "secret")
