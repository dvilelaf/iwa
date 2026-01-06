"""Tests for database operations."""

from unittest.mock import MagicMock, patch

from iwa.core.db import init_db, log_transaction


def test_log_transaction_upsert():
    """Test log_transaction creates new records."""
    with patch("iwa.core.db.SentTransaction") as mock_model:
        mock_model.get_or_none.return_value = None
        mock_insert = mock_model.insert.return_value
        mock_upsert = mock_insert.on_conflict_replace.return_value

        log_transaction("0x123", "0xFrom", "0xTo", "DAI", 100, "gnosis")

        mock_model.insert.assert_called_once()
        _, kwargs = mock_model.insert.call_args
        assert kwargs["tx_hash"] == "0x123"
        assert kwargs["chain"] == "gnosis"

        mock_upsert.execute.assert_called_once()


def test_log_transaction_update_preserve_fields():
    """Test log_transaction preserves existing non-null fields."""
    with patch("iwa.core.db.SentTransaction") as mock_model:
        mock_instance = MagicMock()
        mock_instance.token = "DAI"
        mock_instance.value_eur = 10.0
        mock_instance.amount_wei = "100"
        mock_model.get_or_none.return_value = mock_instance

        # Update with token="NATIVE" which should be ignored if existing is better
        log_transaction("0x123", "0xFrom", "0xTo", "NATIVE", 0, "gnosis")

        mock_model.insert.assert_called_once()
        _, kwargs = mock_model.insert.call_args
        # Should preserve DAI and 100
        assert kwargs["token"] == "DAI"
        assert kwargs["amount_wei"] == "100"


def test_log_transaction_error():
    """Test log_transaction handles errors gracefully."""
    with (
        patch("iwa.core.db.SentTransaction") as mock_model,
        patch("iwa.core.db.logger") as mock_logger,
    ):
        mock_model.get_or_none.side_effect = Exception("DB Error")

        log_transaction("0x123", "0xFrom", "0xTo", "DAI", 100, "gnosis")

        mock_logger.error.assert_called()


def test_init_db():
    """Test init_db creates tables and runs migrations."""
    with (
        patch("iwa.core.db.db") as mock_db,
        patch("iwa.core.db.SentTransaction") as mock_model,
        patch("iwa.core.db.migrate") as mock_migrate,
        patch("iwa.core.db.SqliteMigrator"),
    ):
        mock_db.get_columns.return_value = []

        init_db()

        mock_db.connect.assert_called_once()
        mock_db.create_tables.assert_called_with([mock_model], safe=True)
        assert mock_migrate.call_count >= 1


def test_init_db_closed_at_end():
    """Test init_db closes connection at end."""
    with (
        patch("iwa.core.db.db") as mock_db,
        patch("iwa.core.db.SentTransaction"),
        patch("iwa.core.db.migrate"),
        patch("iwa.core.db.SqliteMigrator"),
    ):
        mock_db.is_closed.side_effect = [True, False]  # closed initially, then open
        mock_db.get_columns.return_value = []

        init_db()

        mock_db.close.assert_called_once()


def test_init_db_get_columns_error():
    """Test init_db handles get_columns error."""
    with (
        patch("iwa.core.db.db") as mock_db,
        patch("iwa.core.db.SentTransaction"),
    ):
        mock_db.get_columns.side_effect = Exception("Table not found")

        # Should not raise
        init_db()


def test_run_migrations_drop_token_symbol():
    """Test run_migrations drops deprecated token_symbol column."""
    from iwa.core.db import run_migrations

    with patch("iwa.core.db.SqliteMigrator"), patch("iwa.core.db.migrate") as mock_migrate:
        columns = ["token_symbol", "from_tag", "price_eur", "tags"]

        run_migrations(columns)

        # Should have called migrate to drop token_symbol
        assert mock_migrate.called


def test_run_migrations_drop_token_symbol_error():
    """Test run_migrations handles drop_column error."""
    from iwa.core.db import run_migrations

    with (
        patch("iwa.core.db.SqliteMigrator"),
        patch("iwa.core.db.migrate", side_effect=Exception("Drop failed")),
        patch("iwa.core.db.logger") as mock_logger,
    ):
        columns = ["token_symbol", "from_tag", "price_eur", "tags"]

        run_migrations(columns)

        mock_logger.warning.assert_called()


def test_run_migrations_add_from_tag():
    """Test run_migrations adds from_tag columns."""
    from iwa.core.db import run_migrations

    with patch("iwa.core.db.SqliteMigrator"), patch("iwa.core.db.migrate") as mock_migrate:
        columns = ["price_eur", "tags"]  # No from_tag

        run_migrations(columns)

        assert mock_migrate.called


def test_run_migrations_add_from_tag_error():
    """Test run_migrations handles add_column error."""
    from iwa.core.db import run_migrations

    with (
        patch("iwa.core.db.SqliteMigrator"),
        patch("iwa.core.db.migrate", side_effect=Exception("Add failed")),
        patch("iwa.core.db.logger") as mock_logger,
    ):
        columns = []  # No columns - triggers add

        run_migrations(columns)

        mock_logger.warning.assert_called()


def test_run_migrations_add_price_eur():
    """Test run_migrations adds price columns."""
    from iwa.core.db import run_migrations

    with patch("iwa.core.db.SqliteMigrator"), patch("iwa.core.db.migrate") as mock_migrate:
        columns = ["from_tag", "tags"]  # No price_eur

        run_migrations(columns)

        assert mock_migrate.called


def test_run_migrations_add_tags():
    """Test run_migrations adds tags column."""
    from iwa.core.db import run_migrations

    with patch("iwa.core.db.SqliteMigrator"), patch("iwa.core.db.migrate") as mock_migrate:
        columns = ["from_tag", "price_eur"]  # No tags

        run_migrations(columns)

        assert mock_migrate.called
