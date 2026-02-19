"""Tests for OlasPlugin to improve coverage.

Covers uncovered lines in plugin.py including:
- _get_safe_signers ValueError branch
- _resolve_staking_name
- _display_service_table and sub-methods (_add_safe_info, _add_staking_info,
  _add_owner_info, _add_agent_info)
- _import_and_print_results (skipped/errors branches)
- _prompt_password_for_verification
- _print_import_summary (with skipped, with errors)
"""

from unittest.mock import MagicMock, call, patch

import pytest
import typer

from iwa.plugins.olas.importer import DiscoveredKey, DiscoveredService, ImportResult
from iwa.plugins.olas.plugin import OlasPlugin

ADDR_SAFE = "0x1111111111111111111111111111111111111111"
ADDR_AGENT = "0x2222222222222222222222222222222222222222"
ADDR_OWNER = "0x3333333333333333333333333333333333333333"
ADDR_STAKING = "0x389B46C259631Acd6a69Bde8B6cEe218230bAE8C"
ADDR_OWNER_SAFE = "0x4444444444444444444444444444444444444444"


@pytest.fixture
def plugin():
    """Create an OlasPlugin instance."""
    return OlasPlugin()


class TestGetSafeSigners:
    """Test _get_safe_signers method."""

    def test_value_error_returns_none_none(self, plugin):
        """Test that ValueError from ChainInterfaces returns (None, None)."""
        with (
            patch("iwa.core.chain.ChainInterfaces") as mock_ci_cls,
        ):
            mock_ci = mock_ci_cls.return_value
            mock_ci.get.side_effect = ValueError("Chain not supported")
            signers, exists = plugin._get_safe_signers(ADDR_SAFE, "unsupported_chain")
            assert signers is None
            assert exists is None


class TestResolveStakingName:
    """Test _resolve_staking_name method."""

    def test_resolves_known_contract(self, plugin):
        """Test resolving a known staking contract address."""
        # ADDR_STAKING is "Hobbyist 1 Legacy (100 OLAS)" on gnosis
        result = plugin._resolve_staking_name(ADDR_STAKING, "gnosis")
        assert result == "Hobbyist 1 Legacy (100 OLAS)"

    def test_returns_none_for_unknown_address(self, plugin):
        """Test returning None for unknown staking address."""
        result = plugin._resolve_staking_name(ADDR_AGENT, "gnosis")
        assert result is None

    def test_returns_none_for_unknown_chain(self, plugin):
        """Test returning None for unknown chain."""
        result = plugin._resolve_staking_name(ADDR_STAKING, "unknown_chain")
        assert result is None

    def test_case_insensitive_match(self, plugin):
        """Test that address matching is case-insensitive."""
        result = plugin._resolve_staking_name(ADDR_STAKING.lower(), "gnosis")
        assert result == "Hobbyist 1 Legacy (100 OLAS)"


class TestAddSafeInfo:
    """Test _add_safe_info method."""

    def test_safe_exists_agent_is_signer(self, plugin):
        """Test when Safe exists and agent is a signer."""
        table = MagicMock()
        agent_key = DiscoveredKey(address=ADDR_AGENT, role="agent")
        service = DiscoveredService(
            safe_address=ADDR_SAFE, keys=[agent_key], chain_name="gnosis"
        )

        with patch.object(
            plugin, "_get_safe_signers", return_value=([ADDR_AGENT], True)
        ):
            signers, exists = plugin._add_safe_info(table, service)

        assert exists is True
        assert signers == [ADDR_AGENT]
        # Table should have one row with "Multisig"
        table.add_row.assert_called_once()
        row_call = table.add_row.call_args
        assert row_call[0][0] == "Multisig"
        assert ADDR_SAFE in row_call[0][1]
        assert "Signer:" in row_call[0][1]

    def test_safe_exists_agent_not_signer(self, plugin):
        """Test when Safe exists but agent is NOT a signer."""
        table = MagicMock()
        agent_key = DiscoveredKey(address=ADDR_AGENT, role="agent")
        service = DiscoveredService(
            safe_address=ADDR_SAFE, keys=[agent_key], chain_name="gnosis"
        )
        other_signer = "0x5555555555555555555555555555555555555555"

        with patch.object(
            plugin, "_get_safe_signers", return_value=([other_signer], True)
        ):
            signers, exists = plugin._add_safe_info(table, service)

        assert exists is True
        row_call = table.add_row.call_args
        assert "NOT A SIGNER" in row_call[0][1]

    def test_safe_does_not_exist(self, plugin):
        """Test when Safe does not exist on-chain."""
        table = MagicMock()
        service = DiscoveredService(
            safe_address=ADDR_SAFE, keys=[], chain_name="gnosis"
        )

        with patch.object(
            plugin, "_get_safe_signers", return_value=([], False)
        ):
            signers, exists = plugin._add_safe_info(table, service)

        assert exists is False
        row_call = table.add_row.call_args
        assert "DOES NOT EXIST ON-CHAIN" in row_call[0][1]

    def test_no_safe_address(self, plugin):
        """Test when service has no safe address."""
        table = MagicMock()
        service = DiscoveredService(safe_address=None, keys=[], chain_name="gnosis")

        signers, exists = plugin._add_safe_info(table, service)

        assert signers is None
        assert exists is None
        row_call = table.add_row.call_args
        assert row_call[0][0] == "Multisig"
        assert "Not detected" in row_call[0][1]

    def test_safe_exists_no_agent_key(self, plugin):
        """Test when Safe exists but there is no agent key."""
        table = MagicMock()
        owner_key = DiscoveredKey(address=ADDR_OWNER, role="owner")
        service = DiscoveredService(
            safe_address=ADDR_SAFE, keys=[owner_key], chain_name="gnosis"
        )

        with patch.object(
            plugin, "_get_safe_signers", return_value=([ADDR_OWNER], True)
        ):
            signers, exists = plugin._add_safe_info(table, service)

        assert exists is True
        # No "NOT A SIGNER" warning since there's no agent key
        row_call = table.add_row.call_args
        assert "NOT A SIGNER" not in row_call[0][1]

    def test_safe_exists_agent_address_without_0x(self, plugin):
        """Test when agent address does not start with 0x."""
        table = MagicMock()
        # Address without 0x prefix
        addr_no_prefix = ADDR_AGENT[2:]  # Remove 0x
        agent_key = DiscoveredKey(address=addr_no_prefix, role="agent")
        service = DiscoveredService(
            safe_address=ADDR_SAFE, keys=[agent_key], chain_name="gnosis"
        )

        with patch.object(
            plugin,
            "_get_safe_signers",
            return_value=([ADDR_AGENT], True),
        ):
            signers, exists = plugin._add_safe_info(table, service)

        assert exists is True
        row_call = table.add_row.call_args
        assert "Signer:" in row_call[0][1]

    def test_rpc_not_configured(self, plugin):
        """Test when RPC is not configured (None, None)."""
        table = MagicMock()
        service = DiscoveredService(
            safe_address=ADDR_SAFE, keys=[], chain_name="gnosis"
        )

        with patch.object(
            plugin, "_get_safe_signers", return_value=(None, None)
        ):
            signers, exists = plugin._add_safe_info(table, service)

        # Neither True nor False for safe_exists means we skip verification
        assert signers is None
        assert exists is None
        row_call = table.add_row.call_args
        # The safe_text should just be the address without any markers
        assert ADDR_SAFE in row_call[0][1]


class TestAddStakingInfo:
    """Test _add_staking_info method."""

    def test_known_staking_contract(self, plugin):
        """Test display with a known staking contract."""
        table = MagicMock()
        service = DiscoveredService(
            staking_contract_address=ADDR_STAKING, chain_name="gnosis"
        )

        plugin._add_staking_info(table, service)

        calls = table.add_row.call_args_list
        assert len(calls) == 2
        assert calls[0][0][0] == "Staking"
        assert "Hobbyist 1 Legacy" in calls[0][0][1]
        assert calls[1][0][0] == "Staking Addr"
        assert ADDR_STAKING in calls[1][0][1]

    def test_unknown_staking_contract(self, plugin):
        """Test display with an unknown staking contract address."""
        table = MagicMock()
        unknown_addr = "0x9999999999999999999999999999999999999999"
        service = DiscoveredService(
            staking_contract_address=unknown_addr, chain_name="gnosis"
        )

        plugin._add_staking_info(table, service)

        calls = table.add_row.call_args_list
        assert "Unknown" in calls[0][0][1]

    def test_no_staking_contract(self, plugin):
        """Test display when no staking contract is configured."""
        table = MagicMock()
        service = DiscoveredService(
            staking_contract_address=None, chain_name="gnosis"
        )

        plugin._add_staking_info(table, service)

        calls = table.add_row.call_args_list
        assert len(calls) == 2
        assert "Not detected" in calls[0][0][1]
        assert "Not detected" in calls[1][0][1]


class TestAddOwnerInfo:
    """Test _add_owner_info method."""

    def test_owner_key_encrypted(self, plugin):
        """Test display with encrypted owner key."""
        table = MagicMock()
        owner_key = DiscoveredKey(
            address=ADDR_OWNER, role="owner", is_encrypted=True
        )
        service = DiscoveredService(keys=[owner_key])

        plugin._add_owner_info(table, service)

        calls = table.add_row.call_args_list
        owner_call = next(c for c in calls if c[0][0] == "Owner (EOA)")
        assert "encrypted" in owner_call[0][1]

    def test_owner_key_plaintext(self, plugin):
        """Test display with plaintext owner key."""
        table = MagicMock()
        owner_key = DiscoveredKey(
            address=ADDR_OWNER, role="owner", is_encrypted=False
        )
        service = DiscoveredService(keys=[owner_key])

        plugin._add_owner_info(table, service)

        calls = table.add_row.call_args_list
        owner_call = next(c for c in calls if c[0][0] == "Owner (EOA)")
        assert "plaintext" in owner_call[0][1]

    def test_owner_key_signature_verified(self, plugin):
        """Test display with signature-verified owner key."""
        table = MagicMock()
        owner_key = DiscoveredKey(
            address=ADDR_OWNER, role="owner", signature_verified=True
        )
        service = DiscoveredService(keys=[owner_key])

        plugin._add_owner_info(table, service)

        calls = table.add_row.call_args_list
        owner_call = next(c for c in calls if c[0][0] == "Owner (EOA)")
        assert "green" in owner_call[0][1]

    def test_no_owner_key_but_has_eoa_address(self, plugin):
        """Test display when no owner key but service_owner_eoa_address set."""
        table = MagicMock()
        service = DiscoveredService(
            keys=[], service_owner_eoa_address=ADDR_OWNER
        )

        plugin._add_owner_info(table, service)

        calls = table.add_row.call_args_list
        owner_call = next(c for c in calls if c[0][0] == "Owner (EOA)")
        assert ADDR_OWNER in owner_call[0][1]

    def test_no_owner_at_all(self, plugin):
        """Test display when there is no owner info at all."""
        table = MagicMock()
        service = DiscoveredService(keys=[])

        plugin._add_owner_info(table, service)

        calls = table.add_row.call_args_list
        owner_call = next(c for c in calls if c[0][0] == "Owner (EOA)")
        assert "N/A" in owner_call[0][1]

    def test_with_safe_owner_exists_signer(self, plugin):
        """Test display when service has a Safe owner and EOA is signer."""
        table = MagicMock()
        owner_key = DiscoveredKey(
            address=ADDR_OWNER, role="owner", is_encrypted=True
        )
        service = DiscoveredService(
            keys=[owner_key],
            service_owner_multisig_address=ADDR_OWNER_SAFE,
            chain_name="gnosis",
        )

        with patch.object(
            plugin, "_get_safe_signers", return_value=([ADDR_OWNER], True)
        ):
            plugin._add_owner_info(table, service)

        calls = table.add_row.call_args_list
        safe_call = next(c for c in calls if c[0][0] == "Owner (Safe)")
        assert ADDR_OWNER_SAFE in safe_call[0][1]
        assert "Signer:" in safe_call[0][1]

    def test_with_safe_owner_exists_not_signer(self, plugin):
        """Test display when service has a Safe owner but EOA is NOT signer."""
        table = MagicMock()
        owner_key = DiscoveredKey(
            address=ADDR_OWNER, role="owner", is_encrypted=True
        )
        other_signer = "0x5555555555555555555555555555555555555555"
        service = DiscoveredService(
            keys=[owner_key],
            service_owner_multisig_address=ADDR_OWNER_SAFE,
            chain_name="gnosis",
        )

        with patch.object(
            plugin, "_get_safe_signers", return_value=([other_signer], True)
        ):
            plugin._add_owner_info(table, service)

        calls = table.add_row.call_args_list
        safe_call = next(c for c in calls if c[0][0] == "Owner (Safe)")
        assert "NOT A SIGNER" in safe_call[0][1]

    def test_with_safe_owner_does_not_exist(self, plugin):
        """Test display when Safe owner does not exist on-chain."""
        table = MagicMock()
        owner_key = DiscoveredKey(address=ADDR_OWNER, role="owner")
        service = DiscoveredService(
            keys=[owner_key],
            service_owner_multisig_address=ADDR_OWNER_SAFE,
            chain_name="gnosis",
        )

        with patch.object(
            plugin, "_get_safe_signers", return_value=([], False)
        ):
            plugin._add_owner_info(table, service)

        calls = table.add_row.call_args_list
        safe_call = next(c for c in calls if c[0][0] == "Owner (Safe)")
        assert "DOES NOT EXIST" in safe_call[0][1]

    def test_no_safe_owner(self, plugin):
        """Test display when no Safe owner address."""
        table = MagicMock()
        service = DiscoveredService(keys=[])

        plugin._add_owner_info(table, service)

        calls = table.add_row.call_args_list
        safe_call = next(c for c in calls if c[0][0] == "Owner (Safe)")
        assert "N/A" in safe_call[0][1]

    def test_owner_key_address_without_0x(self, plugin):
        """Test owner key address without 0x prefix in Safe signer check."""
        table = MagicMock()
        addr_no_prefix = ADDR_OWNER[2:]  # Remove 0x
        owner_key = DiscoveredKey(
            address=addr_no_prefix, role="owner", is_encrypted=True
        )
        service = DiscoveredService(
            keys=[owner_key],
            service_owner_multisig_address=ADDR_OWNER_SAFE,
            chain_name="gnosis",
        )

        with patch.object(
            plugin, "_get_safe_signers", return_value=([ADDR_OWNER], True)
        ):
            plugin._add_owner_info(table, service)

        calls = table.add_row.call_args_list
        safe_call = next(c for c in calls if c[0][0] == "Owner (Safe)")
        assert "Signer:" in safe_call[0][1]

    def test_owner_key_not_signer_addr_without_0x(self, plugin):
        """Test owner key not signer with address without 0x prefix."""
        table = MagicMock()
        addr_no_prefix = ADDR_OWNER[2:]  # Remove 0x
        owner_key = DiscoveredKey(
            address=addr_no_prefix, role="owner", is_encrypted=True
        )
        other_signer = "0x5555555555555555555555555555555555555555"
        service = DiscoveredService(
            keys=[owner_key],
            service_owner_multisig_address=ADDR_OWNER_SAFE,
            chain_name="gnosis",
        )

        with patch.object(
            plugin, "_get_safe_signers", return_value=([other_signer], True)
        ):
            plugin._add_owner_info(table, service)

        calls = table.add_row.call_args_list
        safe_call = next(c for c in calls if c[0][0] == "Owner (Safe)")
        assert "NOT A SIGNER" in safe_call[0][1]
        # Should have 0x prepended for display
        assert "0x" in safe_call[0][1]


class TestAddAgentInfo:
    """Test _add_agent_info method."""

    def test_agent_encrypted(self, plugin):
        """Test agent key display when encrypted."""
        table = MagicMock()
        agent_key = DiscoveredKey(
            address=ADDR_AGENT, role="agent", is_encrypted=True
        )
        service = DiscoveredService(keys=[agent_key])

        plugin._add_agent_info(table, service, None, None)

        row_call = table.add_row.call_args
        assert row_call[0][0] == "Agent"
        assert "encrypted" in row_call[0][1]

    def test_agent_signature_verified(self, plugin):
        """Test agent key display when signature is verified."""
        table = MagicMock()
        agent_key = DiscoveredKey(
            address=ADDR_AGENT, role="agent", signature_verified=True
        )
        service = DiscoveredService(keys=[agent_key])

        plugin._add_agent_info(table, service, None, None)

        row_call = table.add_row.call_args
        assert "green" in row_call[0][1]

    def test_agent_plaintext_unverified(self, plugin):
        """Test agent key display when plaintext and unverified."""
        table = MagicMock()
        agent_key = DiscoveredKey(
            address=ADDR_AGENT, role="agent", is_encrypted=False
        )
        service = DiscoveredService(keys=[agent_key])

        plugin._add_agent_info(table, service, None, None)

        row_call = table.add_row.call_args
        assert "red" in row_call[0][1]

    def test_agent_not_signer_safe_doesnt_exist(self, plugin):
        """Test agent display when safe doesn't exist (safe_exists=False)."""
        table = MagicMock()
        agent_key = DiscoveredKey(
            address=ADDR_AGENT, role="agent", is_encrypted=True
        )
        service = DiscoveredService(
            keys=[agent_key], safe_address=ADDR_SAFE
        )

        plugin._add_agent_info(table, service, [], False)

        row_call = table.add_row.call_args
        assert "NOT A SIGNER" in row_call[0][1]

    def test_agent_not_signer_on_chain(self, plugin):
        """Test agent display when on-chain check shows not a signer."""
        table = MagicMock()
        agent_key = DiscoveredKey(
            address=ADDR_AGENT, role="agent", is_encrypted=True
        )
        other_signer = "0x5555555555555555555555555555555555555555"
        service = DiscoveredService(
            keys=[agent_key], safe_address=ADDR_SAFE
        )

        plugin._add_agent_info(table, service, [other_signer], True)

        row_call = table.add_row.call_args
        assert "NOT A SIGNER" in row_call[0][1]

    def test_agent_is_signer_on_chain(self, plugin):
        """Test agent display when on-chain check shows agent is a signer."""
        table = MagicMock()
        agent_key = DiscoveredKey(
            address=ADDR_AGENT, role="agent", is_encrypted=True
        )
        service = DiscoveredService(
            keys=[agent_key], safe_address=ADDR_SAFE
        )

        plugin._add_agent_info(table, service, [ADDR_AGENT], True)

        row_call = table.add_row.call_args
        # Should NOT have "NOT A SIGNER"
        assert "NOT A SIGNER" not in row_call[0][1]

    def test_no_agent_key(self, plugin):
        """Test display when no agent key exists."""
        table = MagicMock()
        service = DiscoveredService(keys=[])

        plugin._add_agent_info(table, service, None, None)

        row_call = table.add_row.call_args
        assert "Not detected" in row_call[0][1]


class TestDisplayServiceTable:
    """Test _display_service_table method."""

    def test_full_display(self, plugin):
        """Test full service table display."""
        console = MagicMock()
        agent_key = DiscoveredKey(address=ADDR_AGENT, role="agent")
        service = DiscoveredService(
            service_id=1,
            service_name="Test Service",
            chain_name="gnosis",
            safe_address=ADDR_SAFE,
            staking_contract_address=ADDR_STAKING,
            keys=[agent_key],
            format="trader_runner",
        )

        with patch.object(
            plugin, "_get_safe_signers", return_value=(None, None)
        ):
            plugin._display_service_table(console, service, 1)

        # Console.print should be called at least twice (table + newline)
        assert console.print.call_count >= 2


class TestImportAndPrintResults:
    """Test _import_and_print_results method."""

    def test_successful_import(self, plugin):
        """Test import with keys, safes, and services."""
        console = MagicMock()
        importer = MagicMock()
        service = DiscoveredService(service_name="TestSvc")

        importer.import_service.return_value = ImportResult(
            success=True,
            message="OK",
            imported_keys=["0xKey1"],
            imported_safes=["0xSafe1"],
            imported_services=["gnosis:1"],
        )

        result = plugin._import_and_print_results(
            console, importer, [service], "password"
        )
        total_keys, total_safes, total_services, all_skipped, all_errors = result

        assert total_keys == 1
        assert total_safes == 1
        assert total_services == 1
        assert all_skipped == []
        assert all_errors == []

    def test_import_with_skipped_items(self, plugin):
        """Test import when some items are skipped."""
        console = MagicMock()
        importer = MagicMock()
        service = DiscoveredService(service_name="TestSvc")

        importer.import_service.return_value = ImportResult(
            success=True,
            message="OK",
            skipped=["Key 0x1 (already exists)"],
        )

        result = plugin._import_and_print_results(
            console, importer, [service], "password"
        )
        _, _, _, all_skipped, _ = result

        assert len(all_skipped) == 1
        assert "already exists" in all_skipped[0]

    def test_import_with_errors(self, plugin):
        """Test import when errors occur."""
        console = MagicMock()
        importer = MagicMock()
        service = DiscoveredService(service_name="TestSvc")

        importer.import_service.return_value = ImportResult(
            success=False,
            message="Failed",
            errors=["Key 0x1: decryption failed"],
        )

        result = plugin._import_and_print_results(
            console, importer, [service], "password"
        )
        _, _, _, _, all_errors = result

        assert len(all_errors) == 1
        assert "decryption failed" in all_errors[0]

    def test_multiple_services(self, plugin):
        """Test import of multiple services."""
        console = MagicMock()
        importer = MagicMock()
        svc1 = DiscoveredService(service_name="Svc1")
        svc2 = DiscoveredService(service_name="Svc2")

        importer.import_service.side_effect = [
            ImportResult(
                success=True,
                message="OK",
                imported_keys=["0xKey1"],
                imported_services=["gnosis:1"],
            ),
            ImportResult(
                success=True,
                message="OK",
                imported_keys=["0xKey2"],
                imported_safes=["0xSafe2"],
                imported_services=["gnosis:2"],
            ),
        ]

        result = plugin._import_and_print_results(
            console, importer, [svc1, svc2], "password"
        )
        total_keys, total_safes, total_services, _, _ = result

        assert total_keys == 2
        assert total_safes == 1
        assert total_services == 2


class TestPromptPasswordForVerification:
    """Test _prompt_password_for_verification method."""

    def test_returns_password_when_entered(self, plugin):
        """Test that password is returned when user enters one."""
        with patch("iwa.plugins.olas.plugin.typer.prompt", return_value="secret"):
            result = plugin._prompt_password_for_verification()
        assert result == "secret"

    def test_returns_none_when_empty(self, plugin):
        """Test that None is returned when user presses Enter."""
        with patch("iwa.plugins.olas.plugin.typer.prompt", return_value=""):
            result = plugin._prompt_password_for_verification()
        assert result is None


class TestPrintImportSummary:
    """Test _print_import_summary method."""

    def test_basic_summary(self, plugin):
        """Test basic summary without skipped or errors."""
        console = MagicMock()
        plugin._print_import_summary(console, 3, 2, 1, [], [])

        # Check that the console.print was called with summary info
        printed_texts = [str(c) for c in console.print.call_args_list]
        all_text = " ".join(printed_texts)
        assert "Summary" in all_text

    def test_summary_with_skipped(self, plugin):
        """Test summary includes skipped count."""
        console = MagicMock()
        plugin._print_import_summary(
            console, 1, 0, 0, ["key1 skipped"], []
        )

        printed_texts = [str(c[0][0]) for c in console.print.call_args_list]
        all_text = " ".join(printed_texts)
        assert "Skipped" in all_text

    def test_summary_with_errors_raises_exit(self, plugin):
        """Test summary with errors raises typer.Exit(code=1)."""
        from click.exceptions import Exit

        console = MagicMock()
        with pytest.raises(Exit):
            plugin._print_import_summary(
                console, 0, 0, 0, [], ["error1"]
            )
