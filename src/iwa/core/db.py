"""Database models and utilities."""

import json
from datetime import datetime

from loguru import logger
from peewee import (
    CharField,
    DateTimeField,
    FloatField,
    Model,
    SqliteDatabase,
)
from playhouse.migrate import SqliteMigrator, migrate

from iwa.core.constants import DATA_DIR

# Database stored in data directory alongside other data files
DB_PATH = DATA_DIR / "activity.db"

db = SqliteDatabase(
    str(DB_PATH),
    pragmas={
        "journal_mode": "wal",
        "cache_size": -1 * 64000,
        "foreign_keys": 1,
        "ignore_check_constraints": 0,
        "synchronous": 0,
        "busy_timeout": 5000,
    },
)


class BaseModel(Model):
    """Base Peewee model."""

    class Meta:
        """Meta configuration."""

        database = db


class SentTransaction(BaseModel):
    """Model for sent transactions."""

    tx_hash = CharField(primary_key=True)
    from_address = CharField(index=True)
    from_tag = CharField(null=True)
    to_address = CharField(index=True)
    to_tag = CharField(null=True)
    token = CharField()  # Contract Address (ERC20) or Symbol (Native)
    amount_wei = CharField()  # Store as string to avoid precision loss
    chain = CharField()
    timestamp = DateTimeField(default=datetime.now)
    status = CharField(default="Pending")
    # Pricing info
    price_eur = FloatField(null=True)
    value_eur = FloatField(null=True)
    gas_cost = CharField(null=True)  # Wei
    gas_value_eur = FloatField(null=True)
    tags = CharField(null=True)  # JSON-encoded list of strings
    extra_data = CharField(null=True)  # JSON-encoded dictionary for arbitrary metadata


def _migration_drop_deprecated_columns(migrator: SqliteMigrator, columns: list[str]) -> None:
    """Drop deprecated columns."""
    if "token_symbol" in columns:
        try:
            migrate(migrator.drop_column("senttransaction", "token_symbol"))
        except Exception as e:
            logger.warning(f"Migration (drop token_symbol) failed: {e}")


def _migration_add_tag_columns(migrator: SqliteMigrator, columns: list[str]) -> None:
    """Add from_tag, to_tag, and token_symbol columns."""
    if "from_tag" not in columns:
        try:
            migrate(
                migrator.add_column("senttransaction", "from_tag", CharField(null=True)),
                migrator.add_column("senttransaction", "to_tag", CharField(null=True)),
                migrator.add_column("senttransaction", "token_symbol", CharField(null=True)),
            )
        except Exception as e:
            logger.warning(f"Migration (tags/symbol) failed: {e}")


def _migration_add_pricing_columns(migrator: SqliteMigrator, columns: list[str]) -> None:
    """Add pricing related columns."""
    if "price_eur" not in columns:
        try:
            migrate(
                migrator.add_column("senttransaction", "price_eur", FloatField(null=True)),
                migrator.add_column("senttransaction", "value_eur", FloatField(null=True)),
                migrator.add_column("senttransaction", "gas_cost", CharField(null=True)),
                migrator.add_column("senttransaction", "gas_value_eur", FloatField(null=True)),
            )
        except Exception as e:
            logger.warning(f"Migration (pricing) failed: {e}")


def _migration_add_tags_column(migrator: SqliteMigrator, columns: list[str]) -> None:
    """Add tags column."""
    if "tags" not in columns:
        try:
            migrate(migrator.add_column("senttransaction", "tags", CharField(null=True)))
        except Exception as e:
            logger.warning(f"Migration (tags) failed: {e}")


def _migration_add_extra_data_column(migrator: SqliteMigrator, columns: list[str]) -> None:
    """Add extra_data column."""
    if "extra_data" not in columns:
        try:
            migrate(migrator.add_column("senttransaction", "extra_data", CharField(null=True)))
        except Exception as e:
            logger.warning(f"Migration (extra_data) failed: {e}")


def run_migrations(columns: list[str]) -> None:
    """Run database migrations."""
    migrator = SqliteMigrator(db)

    migrations = [
        _migration_drop_deprecated_columns,
        _migration_add_tag_columns,
        _migration_add_pricing_columns,
        _migration_add_tags_column,
        _migration_add_extra_data_column,
    ]

    for migration in migrations:
        migration(migrator, columns)


def init_db():
    """Initialize the database."""
    if db.is_closed():
        db.connect()
    db.create_tables([SentTransaction], safe=True)

    # Simple migration: check if columns exist, if not add them
    try:
        columns = [c.name for c in db.get_columns("senttransaction")]
        run_migrations(columns)
    except Exception:
        pass

    if not db.is_closed():
        db.close()


def _get_existing_transaction_data(tx_hash: str) -> tuple[SentTransaction | None, list, dict]:
    """Retrieve existing transaction and parse its tags/extra_data."""
    if not tx_hash.startswith("0x"):
        tx_hash = "0x" + tx_hash

    existing = SentTransaction.get_or_none(SentTransaction.tx_hash == tx_hash)
    existing_tags = []
    existing_extra = {}

    if existing:
        if existing.tags:
            try:
                existing_tags = json.loads(existing.tags)
            except Exception:
                existing_tags = []
        if existing.extra_data:
            try:
                existing_extra = json.loads(existing.extra_data)
            except Exception:
                existing_extra = {}

    return existing, existing_tags, existing_extra


def _merge_transaction_tags(existing_tags: list, new_tags: list | None) -> list:
    """Merge existing and new tags."""
    tags_to_add = list(new_tags) if new_tags else []
    return list(set(existing_tags + tags_to_add))


def _merge_transaction_extra_data(existing_extra: dict, new_extra: dict | None) -> dict:
    """Merge existing and new extra_data."""
    extra_to_add = new_extra if new_extra else {}
    return {**existing_extra, **extra_to_add}


def _resolve_final_token_and_amount(
    existing: SentTransaction | None,
    token: str,
    amount_wei: int,
    price_eur: float | None,
    value_eur: float | None,
) -> tuple[str, str, float | None, float | None]:
    """Resolve token name and amount, preserving ERC20 info over native currency if needed."""
    final_token = token
    final_amount_wei = str(amount_wei)
    final_price_eur = price_eur
    final_value_eur = value_eur

    # Native currency names that should not overwrite ERC20 tokens
    native_tokens = {"TOKEN", "NATIVE", "xDAI", "ETH", "XDAI"}

    if existing and existing.token:
        # If existing token is a real ERC20 (not native), preserve it
        if existing.token.upper() not in native_tokens and token.upper() in native_tokens:
            final_token = existing.token
            # Force preservation of price and value even if new ones are passed
            final_price_eur = existing.price_eur
            final_value_eur = existing.value_eur
            # Only preserve amount if the new one is 0
            if int(amount_wei) == 0:
                final_amount_wei = existing.amount_wei

    return final_token, final_amount_wei, final_price_eur, final_value_eur


def _prepare_transaction_record(
    tx_hash: str,
    from_addr: str,
    from_tag: str | None,
    to_addr: str,
    to_tag: str | None,
    chain: str,
    gas_cost: str | None,
    gas_value_eur: float | None,
    existing: SentTransaction | None,
    final_token: str,
    final_amount_wei: str,
    final_price_eur: float | None,
    final_value_eur: float | None,
    merged_tags: list,
    merged_extra: dict,
) -> dict:
    """Prepare the dictionary for database insertion."""
    if not tx_hash.startswith("0x"):
        tx_hash = "0x" + tx_hash

    return {
        "tx_hash": tx_hash,
        "from_address": from_addr,
        "from_tag": from_tag or (existing.from_tag if existing else None),
        "to_address": to_addr,
        "to_tag": to_tag or (existing.to_tag if existing else None),
        "token": final_token,
        "status": "Confirmed",
        "amount_wei": final_amount_wei,
        "chain": chain,
        "price_eur": final_price_eur
        if final_price_eur is not None
        else (existing.price_eur if existing else None),
        "value_eur": final_value_eur
        if final_value_eur is not None
        else (existing.value_eur if existing else None),
        "gas_cost": str(gas_cost)
        if gas_cost is not None
        else (existing.gas_cost if existing else None),
        "gas_value_eur": gas_value_eur
        if gas_value_eur is not None
        else (existing.gas_value_eur if existing else None),
        "tags": json.dumps(merged_tags) if merged_tags else (existing.tags if existing else None),
        "extra_data": json.dumps(merged_extra)
        if merged_extra
        else (existing.extra_data if existing else None),
    }


def log_transaction(
    tx_hash,
    from_addr,
    to_addr,
    token,
    amount_wei,
    chain,
    from_tag=None,
    to_tag=None,
    price_eur=None,
    value_eur=None,
    gas_cost=None,
    gas_value_eur=None,
    tags=None,
    extra_data=None,
):
    """Log a transaction to the database (create or update)."""
    try:
        with db:
            existing, existing_tags, existing_extra = _get_existing_transaction_data(tx_hash)

            merged_tags = _merge_transaction_tags(existing_tags, tags)
            merged_extra = _merge_transaction_extra_data(existing_extra, extra_data)

            final_token, final_amount_wei, final_price, final_value = (
                _resolve_final_token_and_amount(existing, token, amount_wei, price_eur, value_eur)
            )

            data = _prepare_transaction_record(
                tx_hash,
                from_addr,
                from_tag,
                to_addr,
                to_tag,
                chain,
                gas_cost,
                gas_value_eur,
                existing,
                final_token,
                final_amount_wei,
                final_price,
                final_value,
                merged_tags,
                merged_extra,
            )

            SentTransaction.insert(**data).on_conflict_replace().execute()

    except Exception as e:
        logger.error(f"Failed to log transaction: {e}")
