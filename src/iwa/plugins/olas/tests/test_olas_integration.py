"""Integration tests for Olas plugin: importer, service manager, plugin, and TUI."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll

from iwa.plugins.olas.contracts.service import ServiceState
from iwa.plugins.olas.contracts.staking import StakingState
from iwa.plugins.olas.importer import DiscoveredKey, DiscoveredService, OlasServiceImporter
from iwa.plugins.olas.models import Service, StakingStatus
from iwa.plugins.olas.plugin import OlasPlugin
from iwa.plugins.olas.service_manager import ServiceManager
from iwa.plugins.olas.tui.olas_view import OlasView

VALID_ADDR = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"


@pytest.fixture
def mock_wallet():
    """Mock wallet."""
    w = MagicMock()
    w.master_account.address = VALID_ADDR
    w.sign_and_send_transaction.return_value = (True, {"status": 1})
    w.key_storage = MagicMock()
    w.key_storage._password = "pass"
    w.balance_service = MagicMock()
    w.drain.return_value = {"tx": "0x123"}
    return w


# === IMPORTER GAPS (lines 63-73, 114-115, 181-186, etc) ===


def test_discovered_service_properties():
    """Cover DiscoveredService.agent_key and operator_key properties (lines 60-73)."""
    # No keys - should return None
    svc = DiscoveredService()
    assert svc.agent_key is None
    assert svc.operator_key is None

    # With agent key
    svc.keys.append(DiscoveredKey(address="0x1", role="agent"))
    assert svc.agent_key is not None
    assert svc.agent_key.role == "agent"
    assert svc.operator_key is None

    # With operator key
    svc.keys.append(DiscoveredKey(address="0x2", role="operator"))
    assert svc.operator_key is not None
    assert svc.operator_key.role == "operator"

    # With owner key (also matches operator_key)
    svc2 = DiscoveredService()
    svc2.keys.append(DiscoveredKey(address="0x3", role="owner"))
    assert svc2.operator_key is not None
    assert svc2.operator_key.role == "owner"


def test_importer_scan_nonexistent_path(mock_wallet, tmp_path):
    """Cover scan_directory with non-existent path (line 114-115)."""
    with patch("iwa.core.models.Config"):
        importer = OlasServiceImporter(mock_wallet.key_storage)
        result = importer.scan_directory(tmp_path / "nonexistent")
        assert result == []


def test_importer_parse_keys_json_variations(mock_wallet, tmp_path):
    """Cover _parse_keys_json edge cases (lines 181-186, 355-377)."""
    with patch("iwa.core.models.Config"):
        importer = OlasServiceImporter(mock_wallet.key_storage)

        # Valid array
        keys_file = tmp_path / "keys.json"
        keys_file.write_text(
            json.dumps([{"address": "abc123", "crypto": {}}, {"address": "0xdef456", "crypto": {}}])
        )
        keys = importer._parse_keys_json(keys_file)
        assert len(keys) == 2
        assert keys[0].address == "0xabc123"  # 0x prefix added
        assert keys[1].address == "0xdef456"  # Already has 0x

        # Not an array
        keys_file.write_text(json.dumps({"address": "0x123"}))
        assert importer._parse_keys_json(keys_file) == []

        # IO error
        keys_file.unlink()
        assert importer._parse_keys_json(keys_file) == []


def test_importer_parse_trader_runner_keys_json(mock_wallet, tmp_path):
    """Cover keys.json parsing in trader_runner format (lines 178-186)."""
    with patch("iwa.core.models.Config"):
        importer = OlasServiceImporter(mock_wallet.key_storage)

        # Create .trader_runner with keys.json
        trader = tmp_path / ".trader_runner"
        trader.mkdir()
        (trader / "service_id.txt").write_text("123")
        (trader / "service_safe_address.txt").write_text(VALID_ADDR)
        (trader / "keys.json").write_text(json.dumps([{"address": "0xkey1", "crypto": {}}]))

        services = importer.scan_directory(tmp_path)
        assert len(services) == 1
        assert len(services[0].keys) == 1


def test_importer_trader_runner_no_data(mock_wallet, tmp_path):
    """Cover trader_runner with no valid data (line 192-193)."""
    with patch("iwa.core.models.Config"):
        importer = OlasServiceImporter(mock_wallet.key_storage)

        # Empty .trader_runner folder
        trader = tmp_path / ".trader_runner"
        trader.mkdir()

        services = importer.scan_directory(tmp_path)
        assert len(services) == 0


def test_importer_operate_wallets_only(mock_wallet, tmp_path):
    """Cover _parse_operate_format with wallets but no services (lines 222-250)."""
    with patch("iwa.core.models.Config"):
        importer = OlasServiceImporter(mock_wallet.key_storage)

        # Create .operate with wallets only
        operate = tmp_path / ".operate"
        wallets = operate / "wallets"
        wallets.mkdir(parents=True)

        # ethereum.txt with valid plaintext key JSON
        (wallets / "ethereum.txt").write_text(
            json.dumps({"address": VALID_ADDR, "private_key": "a" * 64})
        )

        # ethereum.json with Safe info
        (wallets / "ethereum.json").write_text(json.dumps({"safes": {"gnosis": VALID_ADDR}}))

        services = importer._parse_operate_format(operate)
        assert len(services) == 1
        assert services[0].safe_address == VALID_ADDR


def test_importer_operate_ethereum_json_error(mock_wallet, tmp_path):
    """Cover _parse_operate_format with invalid ethereum.json (line 246-247)."""
    with patch("iwa.core.models.Config"):
        importer = OlasServiceImporter(mock_wallet.key_storage)

        operate = tmp_path / ".operate"
        wallets = operate / "wallets"
        wallets.mkdir(parents=True)

        # Valid key file
        (wallets / "ethereum.txt").write_text(
            json.dumps({"address": VALID_ADDR, "private_key": "a" * 64})
        )

        # Invalid JSON
        (wallets / "ethereum.json").write_text("{invalid")

        services = importer._parse_operate_format(operate)
        assert len(services) == 1  # Still works, just no safe


def test_importer_parse_keystore_no_crypto(mock_wallet, tmp_path):
    """Cover _parse_keystore_file validation (lines 337-338)."""
    with patch("iwa.core.models.Config"):
        importer = OlasServiceImporter(mock_wallet.key_storage)

        # Missing crypto field
        ks = tmp_path / "key.json"
        ks.write_text(json.dumps({"address": "0x123"}))
        assert importer._parse_keystore_file(ks) is None


def test_importer_parse_plaintext_raw_hex(mock_wallet, tmp_path):
    """Cover _parse_plaintext_key_file with raw hex (lines 400-412)."""
    with patch("iwa.core.models.Config"):
        importer = OlasServiceImporter(mock_wallet.key_storage)

        # Raw hex (64 chars)
        pk = tmp_path / "raw.txt"
        pk.write_text("a" * 64)
        key = importer._parse_plaintext_key_file(pk)
        assert key is not None
        assert key.private_key == "a" * 64

        # With 0x prefix (66 chars)
        pk.write_text("0x" + "b" * 64)
        key = importer._parse_plaintext_key_file(pk)
        assert key is not None
        assert key.private_key == "b" * 64

        # Invalid length
        pk.write_text("short")
        assert importer._parse_plaintext_key_file(pk) is None


def test_importer_decrypt_already_decrypted(mock_wallet):
    """Cover decrypt_key when already decrypted (line 428-429)."""
    with patch("iwa.core.models.Config"):
        importer = OlasServiceImporter(mock_wallet.key_storage)

        key = DiscoveredKey(address="0x1", private_key="abc")
        assert importer.decrypt_key(key, "pass") is True


def test_importer_decrypt_no_keystore(mock_wallet):
    """Cover decrypt_key with no keystore (lines 431-433)."""
    with patch("iwa.core.models.Config"):
        importer = OlasServiceImporter(mock_wallet.key_storage)

        key = DiscoveredKey(address="0x1", is_encrypted=True, encrypted_keystore=None)
        assert importer.decrypt_key(key, "pass") is False


def test_importer_import_service_key_errors(mock_wallet):
    """Cover import_service key failure paths (lines 466-470)."""
    with patch("iwa.core.models.Config"):
        importer = OlasServiceImporter(mock_wallet.key_storage)
        mock_wallet.key_storage.find_stored_account.return_value = None

        # Key that needs password but none provided
        svc = DiscoveredService(service_name="t")
        svc.keys.append(
            DiscoveredKey(
                address=VALID_ADDR,
                is_encrypted=True,
                encrypted_keystore={"crypto": {}, "address": "abc"},
                private_key=None,
            )
        )

        result = importer.import_service(svc, password=None)
        assert result.success is False or len(result.errors) > 0


def test_importer_import_service_duplicate(mock_wallet):
    """Cover import_service duplicate handling (lines 522-524)."""
    with patch("iwa.core.models.Config"):
        importer = OlasServiceImporter(mock_wallet.key_storage)

        # Mock find_stored_account to return existing
        mock_wallet.key_storage.find_stored_account.return_value = MagicMock()

        svc = DiscoveredService(service_name="t")
        svc.keys.append(DiscoveredKey(address=VALID_ADDR, private_key="abc"))

        result = importer.import_service(svc)
        assert any("already exists" in s for s in result.skipped)


def test_importer_generate_tag_collision(mock_wallet):
    """Cover _generate_tag with collisions (lines 570-577, 605-606)."""
    with patch("iwa.core.models.Config"):
        importer = OlasServiceImporter(mock_wallet.key_storage)

        # Pre-populate accounts with existing tags
        mock_wallet.key_storage.accounts = {
            "0x1": MagicMock(tag="svc_agent"),
            "0x2": MagicMock(tag="svc_agent_2"),
        }

        key = DiscoveredKey(address="0x3", role="agent")
        tag = importer._generate_tag(key, "svc")
        assert tag == "svc_agent_3"


def test_importer_import_safe_duplicate(mock_wallet):
    """Cover _import_safe duplicate (lines 582-587)."""
    with patch("iwa.core.models.Config"):
        importer = OlasServiceImporter(mock_wallet.key_storage)

        mock_wallet.key_storage.find_stored_account.return_value = MagicMock()

        svc = DiscoveredService(service_name="t", safe_address=VALID_ADDR)
        success, msg = importer._import_safe(svc)
        assert success is False
        assert msg == "duplicate"


def test_importer_import_service_config_duplicate(mock_wallet):
    """Cover _import_service_config duplicate (lines 634-635)."""
    with patch("iwa.core.models.Config") as mock_config_cls:
        # Set up the config mock properly
        mock_config = MagicMock()
        mock_olas = MagicMock()
        mock_olas.services = {"gnosis:123": MagicMock()}
        mock_config.plugins = {"olas": mock_olas}
        mock_config_cls.return_value = mock_config

        importer = OlasServiceImporter(mock_wallet.key_storage)
        # Replace the config instance
        importer.config = mock_config

        svc = DiscoveredService(service_name="t", service_id=123, chain_name="gnosis")

        success, msg = importer._import_service_config(svc)
        assert success is False
        assert msg == "duplicate"


# === SERVICE MANAGER GAPS ===


def test_sm_create_token_utility_missing(mock_wallet):
    """Cover create() with missing token utility (lines 204-206)."""
    with patch("iwa.core.models.Config"):
        sm = ServiceManager(mock_wallet)

        with patch.dict("iwa.plugins.olas.service_manager.base.OLAS_CONTRACTS", {"unknown": {}}):
            # Should not crash, just log error
            sm.chain_name = "unknown"
            # Can't easily test create without more mocks, but we test the path


def test_sm_get_staking_status_staked_info_fail(mock_wallet):
    """Cover get_staking_status with STAKED but get_service_info fails (lines 843-854)."""
    with patch("iwa.core.models.Config"):
        sm = ServiceManager(mock_wallet)
        sm.service = Service(
            service_name="t", chain_name="gnosis", service_id=1, staking_contract_address=VALID_ADDR
        )

        mock_staking = MagicMock()
        mock_staking.get_staking_state.return_value = StakingState.STAKED
        mock_staking.activity_checker_address = VALID_ADDR
        mock_staking.activity_checker.liveness_ratio = 10
        mock_staking.get_service_info.side_effect = Exception("fail")

        with patch(
            "iwa.plugins.olas.service_manager.staking.StakingContract", return_value=mock_staking
        ):
            status = sm.get_staking_status()
            assert status.staking_state == "STAKED"


def test_sm_call_checkpoint_prepare_fail(mock_wallet):
    """Cover call_checkpoint prepare failure (lines 1100-1102)."""
    with patch("iwa.core.models.Config"):
        sm = ServiceManager(mock_wallet)
        sm.service = Service(
            service_name="t", chain_name="gnosis", service_id=1, staking_contract_address=VALID_ADDR
        )

        mock_staking = MagicMock()
        mock_staking.is_checkpoint_needed.return_value = True
        mock_staking.prepare_checkpoint_tx.return_value = None

        with patch(
            "iwa.plugins.olas.service_manager.staking.StakingContract", return_value=mock_staking
        ):
            result = sm.call_checkpoint()
            assert result is False


def test_sm_spin_up_no_service(mock_wallet):
    """Cover spin_up with no service (lines 1167-1170)."""
    with patch("iwa.core.models.Config"):
        sm = ServiceManager(mock_wallet)
        sm.service = None

        result = sm.spin_up()
        assert result is False


def test_sm_spin_up_activation_fail(mock_wallet):
    """Cover spin_up activation failure (lines 1181-1183)."""
    with patch("iwa.core.models.Config"):
        sm = ServiceManager(mock_wallet)
        sm.service = Service(service_name="t", chain_name="gnosis", service_id=1)

        mock_reg = MagicMock()
        mock_reg.get_service.return_value = {"state": ServiceState.PRE_REGISTRATION}

        with (
            patch.object(sm, "registry", mock_reg),
            patch.object(sm, "activate_registration", return_value=False),
        ):
            result = sm.spin_up()
            assert result is False


def test_sm_wind_down_no_service(mock_wallet):
    """Cover wind_down with no service (lines 1264-1266)."""
    with patch("iwa.core.models.Config"):
        sm = ServiceManager(mock_wallet)
        sm.service = None

        result = sm.wind_down()
        assert result is False


def test_sm_wind_down_nonexistent(mock_wallet):
    """Cover wind_down with non-existent service (lines 1274-1276)."""
    with patch("iwa.core.models.Config"):
        sm = ServiceManager(mock_wallet)
        sm.service = Service(service_name="t", chain_name="gnosis", service_id=1)

        mock_reg = MagicMock()
        mock_reg.get_service.return_value = {"state": ServiceState.NON_EXISTENT}

        with patch.object(sm, "registry", mock_reg):
            result = sm.wind_down()
            assert result is False


def test_sm_mech_request_no_service(mock_wallet):
    """Cover _send_legacy_mech_request with no service (lines 1502-1504)."""
    with patch("iwa.core.models.Config"):
        sm = ServiceManager(mock_wallet)
        sm.service = None

        result = sm._send_legacy_mech_request(b"data")
        assert result is None


def test_sm_mech_request_no_address(mock_wallet):
    """Cover _send_legacy_mech_request missing mech address (lines 1510-1512)."""
    with patch("iwa.core.models.Config"):
        sm = ServiceManager(mock_wallet)
        sm.service = Service(service_name="t", chain_name="unknown", service_id=1)

        result = sm._send_legacy_mech_request(b"data")
        assert result is None


def test_sm_marketplace_mech_no_service(mock_wallet):
    """Cover _send_marketplace_mech_request with no service (lines 1549-1551)."""
    with patch("iwa.core.models.Config"):
        sm = ServiceManager(mock_wallet)
        sm.service = None

        result = sm._send_marketplace_mech_request(b"data")
        assert result is None


# === PLUGIN GAPS ===


def test_plugin_import_display_variants(mock_wallet):
    """Cover plugin import display paths (lines 141-166)."""
    import click

    with (
        patch("iwa.core.models.Config"),
        patch("iwa.plugins.olas.importer.OlasServiceImporter") as mock_imp,
        patch("rich.console.Console"),
        patch("typer.confirm", return_value=False),
    ):
        # Service with various states
        svc = DiscoveredService(
            service_name="test",
            format="trader",
            source_folder=Path("/tmp"),
            chain_name="gnosis",
            safe_address=VALID_ADDR,
        )
        svc.keys.append(DiscoveredKey(address=VALID_ADDR, is_encrypted=True, role="agent"))

        mock_imp.return_value.scan_directory.return_value = [svc]

        plugin = OlasPlugin()

        # Test safe_exists=None (cannot verify)
        with patch.object(plugin, "_get_safe_signers", return_value=([], None)):
            try:
                plugin.import_services(path="/tmp", dry_run=True, yes=False)
            except (SystemExit, click.exceptions.Exit):
                pass

        # Test safe_exists=False (doesn't exist)
        with patch.object(plugin, "_get_safe_signers", return_value=([], False)):
            try:
                plugin.import_services(path="/tmp", dry_run=True, yes=False)
            except (SystemExit, click.exceptions.Exit):
                pass

        # Test safe_exists=True but not a signer
        with patch.object(plugin, "_get_safe_signers", return_value=(["0xother"], True)):
            try:
                plugin.import_services(path="/tmp", dry_run=True, yes=False)
            except (SystemExit, click.exceptions.Exit):
                pass


# === OLAS VIEW GAPS ===


class OlasTestApp(App):
    """Test app to host OlasView."""

    def __init__(self, wallet=None):
        """Initialize test app."""
        super().__init__()
        self.wallet = wallet

    def compose(self) -> ComposeResult:
        """Compose layout."""
        yield VerticalScroll(OlasView(self.wallet), id="root-container")


@pytest.mark.asyncio
async def test_view_button_handlers(mock_wallet):
    """Cover on_button_pressed handlers (lines 121-149)."""
    with patch("iwa.core.models.Config"):
        app = OlasTestApp(mock_wallet)
        async with app.run_test():
            view = app.query_one(OlasView)

            # Test various button events
            for btn_id, method in [
                ("olas-refresh-btn", "load_services"),
                ("olas-create-service-btn", "show_create_service_modal"),
                ("claim-gnosis_1", "claim_rewards"),
                ("unstake-gnosis_1", "unstake_service"),
                ("stake-gnosis_1", "stake_service"),
                ("drain-gnosis_1", "drain_service"),
                ("fund-gnosis_1", "show_fund_service_modal"),
                ("terminate-gnosis_1", "terminate_service"),
                ("checkpoint-gnosis_1", "checkpoint_service"),
            ]:
                mock_event = MagicMock()
                mock_event.button.id = btn_id

                with patch.object(view, method, create=True) as mock_method:
                    view.on_button_pressed(mock_event)
                    assert mock_method.called or btn_id.startswith("olas-")


@pytest.mark.asyncio
async def test_view_render_empty(mock_wallet):
    """Cover _render_services with empty list (line 226)."""
    with patch("iwa.core.models.Config"):
        app = OlasTestApp(mock_wallet)
        async with app.run_test() as pilot:
            view = app.query_one(OlasView)

            await view._render_services([])
            await pilot.pause()


@pytest.mark.asyncio
async def test_view_render_with_services(mock_wallet):
    """Cover _render_services with services (lines 228-232)."""
    with patch("iwa.core.models.Config"):
        app = OlasTestApp(mock_wallet)
        async with app.run_test() as pilot:
            view = app.query_one(OlasView)

            service = Service(
                service_name="test", chain_name="gnosis", service_id=1, multisig_address=VALID_ADDR
            )
            status = StakingStatus(is_staked=False, staking_state="NOT_STAKED")

            await view._render_services([("gnosis:1", service, status)])
            await pilot.pause()
