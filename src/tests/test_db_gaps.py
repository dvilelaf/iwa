"""Tests for database gaps: log_transaction analytics, tag preservation, JSON serialization."""

import json
from unittest.mock import MagicMock, patch

from iwa.core.db import (
    _merge_transaction_extra_data,
    _merge_transaction_tags,
    _prepare_transaction_record,
    _resolve_final_token_and_amount,
    log_transaction,
)

# ---- Tag merging ----


class TestMergeTags:
    def test_merge_empty_existing_with_new(self):
        result = _merge_transaction_tags([], ["swap", "cowswap"])
        assert set(result) == {"swap", "cowswap"}

    def test_merge_existing_with_new_deduplicates(self):
        result = _merge_transaction_tags(["swap"], ["swap", "olas"])
        assert set(result) == {"swap", "olas"}

    def test_merge_with_none_new_tags(self):
        result = _merge_transaction_tags(["existing"], None)
        assert result == ["existing"]

    def test_merge_both_empty(self):
        result = _merge_transaction_tags([], None)
        assert result == []


# ---- Extra data merging ----


class TestMergeExtraData:
    def test_merge_new_data_into_existing(self):
        existing = {"type": "swap"}
        new = {"platform": "cowswap"}
        result = _merge_transaction_extra_data(existing, new)
        assert result == {"type": "swap", "platform": "cowswap"}

    def test_new_data_overrides_existing_keys(self):
        existing = {"type": "swap", "v": 1}
        new = {"v": 2}
        result = _merge_transaction_extra_data(existing, new)
        assert result["v"] == 2

    def test_merge_with_none_new_data(self):
        existing = {"type": "swap"}
        result = _merge_transaction_extra_data(existing, None)
        assert result == {"type": "swap"}

    def test_merge_both_empty(self):
        result = _merge_transaction_extra_data({}, None)
        assert result == {}


# ---- Token/amount resolution ----


class TestResolveTokenAndAmount:
    def test_preserves_erc20_over_native(self):
        """Existing ERC20 token is preserved when new token is native."""
        existing = MagicMock()
        existing.token = "OLAS"
        existing.amount_wei = "1000"
        existing.price_eur = 1.5
        existing.value_eur = 15.0

        token, amount, price, value = _resolve_final_token_and_amount(
            existing, "xDAI", 0, None, None
        )
        assert token == "OLAS"
        assert amount == "1000"
        assert price == 1.5
        assert value == 15.0

    def test_new_erc20_overwrites_existing_native(self):
        """New ERC20 token overwrites existing native."""
        existing = MagicMock()
        existing.token = "xDAI"

        token, amount, price, value = _resolve_final_token_and_amount(
            existing, "OLAS", 5000, 2.0, 10.0
        )
        assert token == "OLAS"
        assert amount == "5000"
        assert price == 2.0

    def test_no_existing_record(self):
        """First insert uses new values directly."""
        token, amount, price, value = _resolve_final_token_and_amount(
            None, "OLAS", 1000, 1.5, 15.0
        )
        assert token == "OLAS"
        assert amount == "1000"
        assert price == 1.5


# ---- Record preparation ----


class TestPrepareRecord:
    def test_tx_hash_gets_0x_prefix(self):
        """Tx hash without 0x prefix gets it added."""
        record = _prepare_transaction_record(
            tx_hash="abc123",
            from_addr="0xFrom",
            from_tag="from_tag",
            to_addr="0xTo",
            to_tag="to_tag",
            chain="gnosis",
            gas_cost="1000",
            gas_value_eur=0.001,
            existing=None,
            final_token="OLAS",
            final_amount_wei="5000",
            final_price_eur=1.5,
            final_value_eur=7.5,
            merged_tags=["swap"],
            merged_extra={"platform": "cowswap"},
        )
        assert record["tx_hash"] == "0xabc123"
        assert record["tags"] == json.dumps(["swap"])
        assert record["extra_data"] == json.dumps({"platform": "cowswap"})

    def test_preserves_existing_tags_when_from_tag_missing(self):
        """from_tag falls back to existing record's from_tag."""
        existing = MagicMock()
        existing.from_tag = "old_from_tag"
        existing.to_tag = "old_to_tag"
        existing.price_eur = None
        existing.value_eur = None
        existing.gas_cost = None
        existing.gas_value_eur = None
        existing.tags = None
        existing.extra_data = None

        record = _prepare_transaction_record(
            tx_hash="0xabc",
            from_addr="0xFrom",
            from_tag=None,
            to_addr="0xTo",
            to_tag=None,
            chain="gnosis",
            gas_cost=None,
            gas_value_eur=None,
            existing=existing,
            final_token="OLAS",
            final_amount_wei="1000",
            final_price_eur=None,
            final_value_eur=None,
            merged_tags=[],
            merged_extra={},
        )
        assert record["from_tag"] == "old_from_tag"
        assert record["to_tag"] == "old_to_tag"


# ---- JSON serialization in log_transaction ----


class TestLogTransactionJSON:
    @patch("iwa.core.db.SentTransaction")
    def test_tags_serialized_as_json(self, mock_model):
        """Tags are stored as JSON array string."""
        mock_model.get_or_none.return_value = None
        mock_insert = mock_model.insert.return_value
        mock_insert.on_conflict_replace.return_value.execute.return_value = None

        log_transaction(
            "0xHash", "0xFrom", "0xTo", "OLAS", 1000, "gnosis",
            tags=["swap", "cowswap"],
        )

        _, kwargs = mock_model.insert.call_args
        tags = json.loads(kwargs["tags"])
        assert isinstance(tags, list)
        assert "swap" in tags
        assert "cowswap" in tags

    @patch("iwa.core.db.SentTransaction")
    def test_extra_data_serialized_as_json(self, mock_model):
        """Extra data is stored as JSON dict string."""
        mock_model.get_or_none.return_value = None
        mock_insert = mock_model.insert.return_value
        mock_insert.on_conflict_replace.return_value.execute.return_value = None

        log_transaction(
            "0xHash", "0xFrom", "0xTo", "OLAS", 1000, "gnosis",
            extra_data={"type": "swap", "sell_token": "OLAS"},
        )

        _, kwargs = mock_model.insert.call_args
        extra = json.loads(kwargs["extra_data"])
        assert extra["type"] == "swap"
        assert extra["sell_token"] == "OLAS"

    @patch("iwa.core.db.SentTransaction")
    def test_tag_preservation_on_update(self, mock_model):
        """Tags from existing record are merged with new tags."""
        existing = MagicMock()
        existing.tags = json.dumps(["old_tag"])
        existing.extra_data = json.dumps({"old_key": "old_val"})
        existing.token = "OLAS"
        existing.amount_wei = "1000"
        existing.price_eur = 1.5
        existing.value_eur = 15.0
        existing.from_tag = "from"
        existing.to_tag = "to"
        existing.gas_cost = "100"
        existing.gas_value_eur = 0.01

        mock_model.get_or_none.return_value = existing
        mock_insert = mock_model.insert.return_value
        mock_insert.on_conflict_replace.return_value.execute.return_value = None

        log_transaction(
            "0xHash", "0xFrom", "0xTo", "OLAS", 1000, "gnosis",
            tags=["new_tag"],
            extra_data={"new_key": "new_val"},
        )

        _, kwargs = mock_model.insert.call_args
        tags = json.loads(kwargs["tags"])
        assert "old_tag" in tags
        assert "new_tag" in tags
        extra = json.loads(kwargs["extra_data"])
        assert extra["old_key"] == "old_val"
        assert extra["new_key"] == "new_val"
