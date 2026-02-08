"""Comprehensive tests for transaction logging - ensures all critical data is saved.

These tests validate that when ANY transaction happens, we save:
- Gas cost in wei and EUR value
- Token names/tags
- Account names/tags (from_tag, to_tag)
- Price EUR and value EUR for token transfers
- All metadata for tax reporting
"""

from unittest.mock import MagicMock, patch

import pytest


# Test addresses - valid 42-char hex
ADDR_MASTER = "0x1111111111111111111111111111111111111111"
ADDR_TRADER_AGENT = "0x2222222222222222222222222222222222222222"
ADDR_STAKING = "0x3333333333333333333333333333333333333333"
ADDR_MULTISIG = "0x4444444444444444444444444444444444444444"
ADDR_EXTERNAL = "0x5555555555555555555555555555555555555555"


@pytest.fixture
def mock_account_service():
    """Mock account service with tags."""
    service = MagicMock()
    service.get_tag_by_address.side_effect = lambda addr: {
        ADDR_MASTER: "master",
        ADDR_TRADER_AGENT: "trader_alpha_agent",
        ADDR_MULTISIG: "trader_alpha_safe",
        ADDR_STAKING: "staking_contract",
    }.get(addr)
    return service


def test_native_transfer_logs_all_data(mock_account_service):
    """Test native transfer logs: gas cost EUR, from_tag, to_tag."""
    from iwa.core.db import log_transaction

    with patch("iwa.core.db.SentTransaction") as mock_model:
        mock_model.get_or_none.return_value = None
        mock_insert = mock_model.insert.return_value
        mock_upsert = mock_insert.on_conflict_replace.return_value

        # Simulate a native xDAI transfer from master to trader
        log_transaction(
            tx_hash="0xabc123",
            from_addr=ADDR_MASTER,
            to_addr=ADDR_TRADER_AGENT,
            token="xDAI",
            amount_wei=5_000_000_000_000_000_000,  # 5 xDAI
            chain="gnosis",
            from_tag="master",
            to_tag="trader_alpha_agent",
            gas_cost="21000000000000000",  # 0.021 xDAI
            gas_value_eur=0.018,  # ~0.021 * 0.85 EUR/xDAI
            price_eur=0.85,  # xDAI price
            value_eur=4.25,  # 5 * 0.85
            tags=["native-transfer"],
        )

        mock_upsert.execute.assert_called_once()
        _, kwargs = mock_model.insert.call_args

        # Validate ALL critical fields
        assert kwargs["tx_hash"] == "0xabc123"
        assert kwargs["from_address"] == ADDR_MASTER
        assert kwargs["to_address"] == ADDR_TRADER_AGENT
        assert kwargs["token"] == "xDAI"
        assert kwargs["amount_wei"] == "5000000000000000000"
        assert kwargs["chain"] == "gnosis"
        assert kwargs["from_tag"] == "master"
        assert kwargs["to_tag"] == "trader_alpha_agent"
        assert kwargs["gas_cost"] == "21000000000000000"
        assert kwargs["gas_value_eur"] == 0.018
        assert kwargs["price_eur"] == 0.85
        assert kwargs["value_eur"] == 4.25
        assert "native-transfer" in kwargs["tags"]


def test_erc20_transfer_logs_all_data():
    """Test ERC20 transfer logs: token name, price EUR, value EUR, tags."""
    from iwa.core.db import log_transaction

    with patch("iwa.core.db.SentTransaction") as mock_model:
        mock_model.get_or_none.return_value = None
        mock_insert = mock_model.insert.return_value
        mock_upsert = mock_insert.on_conflict_replace.return_value

        # Simulate OLAS transfer from safe to master
        log_transaction(
            tx_hash="0xdef456",
            from_addr=ADDR_MULTISIG,
            to_addr=ADDR_MASTER,
            token="OLAS",
            amount_wei=50_000_000_000_000_000_000,  # 50 OLAS
            chain="gnosis",
            from_tag="trader_alpha_safe",
            to_tag="master",
            gas_cost="150000000000000000",  # 0.15 xDAI
            gas_value_eur=0.127,
            price_eur=1.45,  # OLAS price
            value_eur=72.5,  # 50 * 1.45
            tags=["erc20-transfer", "safe-transaction"],
        )

        mock_upsert.execute.assert_called_once()
        _, kwargs = mock_model.insert.call_args

        assert kwargs["token"] == "OLAS"
        assert kwargs["amount_wei"] == "50000000000000000000"
        assert kwargs["from_tag"] == "trader_alpha_safe"
        assert kwargs["to_tag"] == "master"
        assert kwargs["price_eur"] == 1.45
        assert kwargs["value_eur"] == 72.5
        assert kwargs["gas_cost"] == "150000000000000000"
        assert kwargs["gas_value_eur"] == 0.127
        assert "erc20-transfer" in kwargs["tags"]
        assert "safe-transaction" in kwargs["tags"]


def test_claim_rewards_logs_all_data():
    """Test claim rewards logs: OLAS amount, EUR price at claim time, tags."""
    from iwa.core.db import log_transaction

    with patch("iwa.core.db.SentTransaction") as mock_model:
        mock_model.get_or_none.return_value = None
        mock_insert = mock_model.insert.return_value
        mock_upsert = mock_insert.on_conflict_replace.return_value

        # Simulate OLAS claim from staking to safe
        claimed_amount_wei = 10_000_000_000_000_000_000  # 10 OLAS
        olas_price_at_claim = 1.52  # EUR price at the moment of claim
        value_at_claim = 15.2  # 10 * 1.52

        log_transaction(
            tx_hash="0xghi789",
            from_addr=ADDR_STAKING,
            to_addr=ADDR_MULTISIG,
            token="OLAS",
            amount_wei=claimed_amount_wei,
            chain="gnosis",
            from_tag="staking_contract",
            to_tag="trader_alpha_safe",
            price_eur=olas_price_at_claim,  # CRITICAL for tax reporting
            value_eur=value_at_claim,  # CRITICAL for tax reporting
            tags=["olas_claim_rewards", "staking_reward"],
        )

        mock_upsert.execute.assert_called_once()
        _, kwargs = mock_model.insert.call_args

        # Validate CRITICAL fields for tax reporting
        assert kwargs["tx_hash"] == "0xghi789"
        assert kwargs["token"] == "OLAS"
        assert kwargs["amount_wei"] == "10000000000000000000"
        assert kwargs["from_tag"] == "staking_contract"
        assert kwargs["to_tag"] == "trader_alpha_safe"
        assert kwargs["price_eur"] == 1.52  # Must be present!
        assert kwargs["value_eur"] == 15.2  # Must be present!
        assert "olas_claim_rewards" in kwargs["tags"]
        assert "staking_reward" in kwargs["tags"]


def test_swap_logs_price_data():
    """Test COW swap logs: token prices and values for both sides."""
    from iwa.core.db import log_transaction

    with patch("iwa.core.db.SentTransaction") as mock_model:
        mock_model.get_or_none.return_value = None
        mock_insert = mock_model.insert.return_value
        mock_upsert = mock_insert.on_conflict_replace.return_value

        # Simulate swap: selling OLAS for xDAI
        log_transaction(
            tx_hash="0xjkl012",
            from_addr=ADDR_TRADER_AGENT,
            to_addr="0x9008D19f58AAbD9eD0D60971565AA8510560ab41",  # COW vault
            token="OLAS",
            amount_wei=100_000_000_000_000_000_000,  # 100 OLAS sold
            chain="gnosis",
            from_tag="trader_alpha_agent",
            price_eur=1.48,  # OLAS price at swap
            value_eur=148.0,  # 100 * 1.48
            tags=["swap", "cowswap", "olas", "wxdai"],
            gas_cost="0",  # COW swaps are gasless
            gas_value_eur=0.0,
            extra_data={"buy_token": "wxdai", "buy_amount": "125000000000000000000"},
        )

        mock_upsert.execute.assert_called_once()
        _, kwargs = mock_model.insert.call_args

        assert kwargs["token"] == "OLAS"
        assert kwargs["price_eur"] == 1.48  # Must have price for tax reporting
        assert kwargs["value_eur"] == 148.0
        assert "swap" in kwargs["tags"]
        assert "cowswap" in kwargs["tags"]


def test_contract_call_logs_gas_but_not_value():
    """Test contract calls (approve, checkpoint) log gas but not token value."""
    from iwa.core.db import log_transaction

    with patch("iwa.core.db.SentTransaction") as mock_model:
        mock_model.get_or_none.return_value = None
        mock_insert = mock_model.insert.return_value
        mock_upsert = mock_insert.on_conflict_replace.return_value

        # Simulate checkpoint call
        log_transaction(
            tx_hash="0xmno345",
            from_addr=ADDR_TRADER_AGENT,
            to_addr=ADDR_STAKING,
            token="NATIVE",
            amount_wei=0,  # No value transfer
            chain="gnosis",
            from_tag="trader_alpha_agent",
            to_tag="staking_contract",
            gas_cost="250000000000000000",  # 0.25 xDAI
            gas_value_eur=0.212,
            tags=["olas_call_checkpoint"],
        )

        mock_upsert.execute.assert_called_once()
        _, kwargs = mock_model.insert.call_args

        assert kwargs["amount_wei"] == "0"
        assert kwargs["gas_cost"] == "250000000000000000"
        assert kwargs["gas_value_eur"] == 0.212
        assert kwargs.get("price_eur") is None  # No price for contract calls
        assert kwargs.get("value_eur") is None
        assert "olas_call_checkpoint" in kwargs["tags"]


def test_safe_deployment_logs_gas():
    """Test Safe deployment logs gas cost and tags."""
    from iwa.core.db import log_transaction

    with patch("iwa.core.db.SentTransaction") as mock_model:
        mock_model.get_or_none.return_value = None
        mock_insert = mock_model.insert.return_value
        mock_upsert = mock_insert.on_conflict_replace.return_value

        log_transaction(
            tx_hash="0xpqr678",
            from_addr=ADDR_MASTER,
            to_addr=ADDR_MULTISIG,
            token="xDAI",
            amount_wei=0,
            chain="gnosis",
            from_tag="master",
            to_tag="trader_alpha_safe",
            gas_cost="3500000000000000000",  # 3.5 xDAI (expensive deployment)
            gas_value_eur=2.975,
            tags=["safe-deployment"],
        )

        mock_upsert.execute.assert_called_once()
        _, kwargs = mock_model.insert.call_args

        assert kwargs["from_tag"] == "master"
        assert kwargs["to_tag"] == "trader_alpha_safe"
        assert kwargs["gas_cost"] == "3500000000000000000"
        assert kwargs["gas_value_eur"] == 2.975
        assert "safe-deployment" in kwargs["tags"]


def test_transaction_preserves_erc20_over_native():
    """Test that ERC20 token info is preserved over NATIVE updates."""
    from iwa.core.db import log_transaction

    with patch("iwa.core.db.SentTransaction") as mock_model:
        # First call: logs OLAS transfer
        existing = MagicMock()
        existing.token = "OLAS"
        existing.amount_wei = "50000000000000000000"
        existing.price_eur = 1.45
        existing.value_eur = 72.5
        mock_model.get_or_none.return_value = existing

        mock_insert = mock_model.insert.return_value
        mock_upsert = mock_insert.on_conflict_replace.return_value

        # Second call: tries to update with NATIVE (from gas tracking)
        log_transaction(
            tx_hash="0xdef456",
            from_addr=ADDR_MULTISIG,
            to_addr=ADDR_MASTER,
            token="NATIVE",  # Should NOT overwrite OLAS
            amount_wei=0,
            chain="gnosis",
            from_tag="trader_alpha_safe",
            to_tag="master",
            gas_cost="150000000000000000",
            gas_value_eur=0.127,
        )

        mock_upsert.execute.assert_called_once()
        _, kwargs = mock_model.insert.call_args

        # Should preserve OLAS info
        assert kwargs["token"] == "OLAS"
        assert kwargs["amount_wei"] == "50000000000000000000"
        assert kwargs["price_eur"] == 1.45
        assert kwargs["value_eur"] == 72.5


def test_claim_without_price_still_works():
    """Test that claim still works if price service fails (graceful degradation)."""
    from iwa.core.db import log_transaction

    with patch("iwa.core.db.SentTransaction") as mock_model:
        mock_model.get_or_none.return_value = None
        mock_insert = mock_model.insert.return_value
        mock_upsert = mock_insert.on_conflict_replace.return_value

        # Claim but price service failed
        log_transaction(
            tx_hash="0xstu901",
            from_addr=ADDR_STAKING,
            to_addr=ADDR_MULTISIG,
            token="OLAS",
            amount_wei=10_000_000_000_000_000_000,
            chain="gnosis",
            from_tag="staking_contract",
            to_tag="trader_alpha_safe",
            price_eur=None,  # Price service failed
            value_eur=None,
            tags=["olas_claim_rewards", "staking_reward"],
        )

        mock_upsert.execute.assert_called_once()
        _, kwargs = mock_model.insert.call_args

        # Should still save the transaction
        assert kwargs["token"] == "OLAS"
        assert kwargs["amount_wei"] == "10000000000000000000"
        assert kwargs["price_eur"] is None  # OK to be None if service failed
        assert kwargs["value_eur"] is None
        assert "olas_claim_rewards" in kwargs["tags"]


def test_tags_are_merged_on_update():
    """Test that tags are merged when updating existing transaction."""
    from iwa.core.db import log_transaction

    with patch("iwa.core.db.SentTransaction") as mock_model:
        # Existing transaction with one tag
        existing = MagicMock()
        existing.token = "OLAS"
        existing.amount_wei = "50000000000000000000"
        existing.price_eur = None
        existing.value_eur = None
        existing.tags = '["erc20-transfer"]'
        mock_model.get_or_none.return_value = existing

        mock_insert = mock_model.insert.return_value
        mock_upsert = mock_insert.on_conflict_replace.return_value

        # Update with additional tag
        log_transaction(
            tx_hash="0xvwx234",
            from_addr=ADDR_MULTISIG,
            to_addr=ADDR_MASTER,
            token="OLAS",
            amount_wei=50_000_000_000_000_000_000,
            chain="gnosis",
            tags=["safe-transaction"],  # New tag
        )

        mock_upsert.execute.assert_called_once()
        _, kwargs = mock_model.insert.call_args

        # Tags should be merged
        assert "erc20-transfer" in kwargs["tags"]
        assert "safe-transaction" in kwargs["tags"]


def test_approve_logs_gas_and_tags():
    """Test ERC20 approve logs gas cost and appropriate tags."""
    from iwa.core.db import log_transaction

    with patch("iwa.core.db.SentTransaction") as mock_model:
        mock_model.get_or_none.return_value = None
        mock_insert = mock_model.insert.return_value
        mock_upsert = mock_insert.on_conflict_replace.return_value

        # Simulate OLAS approve for COW vault
        log_transaction(
            tx_hash="0xappr123",
            from_addr=ADDR_TRADER_AGENT,
            to_addr="0x0000000000000000000000000000000000000001",  # Token contract
            token="NATIVE",
            amount_wei=0,  # No value transfer in approve
            chain="gnosis",
            from_tag="trader_alpha_agent",
            to_tag="olas_token",
            gas_cost="80000000000000000",  # 0.08 xDAI
            gas_value_eur=0.068,
            tags=["approve"],
        )

        mock_upsert.execute.assert_called_once()
        _, kwargs = mock_model.insert.call_args

        assert kwargs["from_tag"] == "trader_alpha_agent"
        assert kwargs["to_tag"] == "olas_token"
        assert kwargs["amount_wei"] == "0"
        assert kwargs["gas_cost"] == "80000000000000000"
        assert kwargs["gas_value_eur"] == 0.068
        assert "approve" in kwargs["tags"]


def test_checkpoint_logs_gas_and_tags():
    """Test OLAS checkpoint call logs gas and contract tags."""
    from iwa.core.db import log_transaction

    with patch("iwa.core.db.SentTransaction") as mock_model:
        mock_model.get_or_none.return_value = None
        mock_insert = mock_model.insert.return_value
        mock_upsert = mock_insert.on_conflict_replace.return_value

        # Simulate checkpoint call
        log_transaction(
            tx_hash="0xchkpt456",
            from_addr=ADDR_TRADER_AGENT,
            to_addr=ADDR_STAKING,
            token="NATIVE",
            amount_wei=0,  # No value transfer
            chain="gnosis",
            from_tag="trader_alpha_agent",
            to_tag="staking_contract",
            gas_cost="250000000000000000",  # 0.25 xDAI
            gas_value_eur=0.212,
            tags=["olas_call_checkpoint"],
        )

        mock_upsert.execute.assert_called_once()
        _, kwargs = mock_model.insert.call_args

        assert kwargs["from_tag"] == "trader_alpha_agent"
        assert kwargs["to_tag"] == "staking_contract"
        assert kwargs["amount_wei"] == "0"
        assert kwargs["gas_cost"] == "250000000000000000"
        assert kwargs["gas_value_eur"] == 0.212
        assert "olas_call_checkpoint" in kwargs["tags"]


def test_all_transaction_types_have_to_tag():
    """Verify that all transaction types are configured to save to_tag."""
    from iwa.core.db import log_transaction

    test_cases = [
        ("native_transfer", "native-transfer"),
        ("erc20_transfer", "erc20-transfer"),
        ("claim", "olas_claim_rewards"),
        ("swap", "swap"),
        ("approve", "approve"),
        ("checkpoint", "olas_call_checkpoint"),
        ("safe_deploy", "safe-deployment"),
    ]

    for test_name, tag in test_cases:
        with patch("iwa.core.db.SentTransaction") as mock_model:
            mock_model.get_or_none.return_value = None
            mock_insert = mock_model.insert.return_value
            mock_upsert = mock_insert.on_conflict_replace.return_value

            log_transaction(
                tx_hash=f"0x{test_name}",
                from_addr=ADDR_TRADER_AGENT,
                to_addr=ADDR_MULTISIG,
                token="NATIVE",
                amount_wei=0,
                chain="gnosis",
                from_tag="from_account",
                to_tag="to_account",  # This MUST be present
                tags=[tag],
            )

            _, kwargs = mock_model.insert.call_args
            assert kwargs["from_tag"] == "from_account", f"{test_name} missing from_tag"
            assert kwargs["to_tag"] == "to_account", f"{test_name} missing to_tag"
