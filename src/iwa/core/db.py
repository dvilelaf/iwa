"""Database models and utilities."""

import json
from datetime import datetime
from pathlib import Path

from peewee import (
    CharField,
    DateTimeField,
    FloatField,
    Model,
    SqliteDatabase,
)
from playhouse.migrate import SqliteMigrator, migrate

from iwa.core.constants import WALLET_PATH

# Determine DB path (sibling to wallet.json)
# Assuming WALLET_PATH is like ~/.iwa/wallet.json
# DB will be ~/.iwa/activity.db
DB_PATH = Path(WALLET_PATH).parent / "activity.db"

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


def run_migrations(columns):
    """Run database migrations."""
    migrator = SqliteMigrator(db)

    # Deprecated column cleanup
    if "token_symbol" in columns:
        try:
            migrate(migrator.drop_column("senttransaction", "token_symbol"))
        except Exception as e:
            print(f"Migration (drop token_symbol) failed: {e}")

    if "from_tag" not in columns:
        try:
            migrate(
                migrator.add_column("senttransaction", "from_tag", CharField(null=True)),
                migrator.add_column("senttransaction", "to_tag", CharField(null=True)),
                migrator.add_column("senttransaction", "token_symbol", CharField(null=True)),
            )
        except Exception as e:
            print(f"Migration failed: {e}")

    if "price_eur" not in columns:
        try:
            migrate(
                migrator.add_column("senttransaction", "price_eur", FloatField(null=True)),
                migrator.add_column("senttransaction", "value_eur", FloatField(null=True)),
                migrator.add_column("senttransaction", "gas_cost", CharField(null=True)),
                migrator.add_column("senttransaction", "gas_value_eur", FloatField(null=True)),
            )
        except Exception as e:
            print(f"Migration (pricing) failed: {e}")

    if "tags" not in columns:
        try:
            migrate(migrator.add_column("senttransaction", "tags", CharField(null=True)))
        except Exception as e:
            print(f"Migration (tags) failed: {e}")


def init_db():
    """Initialize the database."""
    db.connect()
    db.create_tables([SentTransaction], safe=True)

    # Simple migration: check if columns exist, if not add them
    columns = [c.name for c in db.get_columns("senttransaction")]
    run_migrations(columns)

    db.close()


def log_transaction(  # noqa: D103
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
):
    try:
        if tx_hash and not tx_hash.startswith("0x"):
            tx_hash = "0x" + tx_hash

        with db:
            # Try to get existing transaction to preserve tags
            existing = SentTransaction.get_or_none(SentTransaction.tx_hash == tx_hash)
            existing_tags = []
            if existing and existing.tags:
                try:
                    existing_tags = json.loads(existing.tags)
                except Exception:
                    existing_tags = []

            # Merge tags
            new_tags = list(tags) if tags else []
            merged_tags = list(set(existing_tags + new_tags))

            # Smart token resolution: don't let 0-value "NATIVE" update overwrite a real token
            final_token = token
            final_amount_wei = str(amount_wei)

            if existing and existing.token and existing.token not in ["TOKEN", "NATIVE"]:
                # If we have a real token already, and the new one is native with 0 value
                if token in ["TOKEN", "NATIVE", "xDAI", "ETH"] and int(amount_wei) == 0:
                    final_token = existing.token
                    final_amount_wei = existing.amount_wei

            data = {
                "tx_hash": tx_hash,
                "from_address": from_addr,
                "from_tag": from_tag or (existing.from_tag if existing else None),
                "to_address": to_addr,
                "to_tag": to_tag or (existing.to_tag if existing else None),
                "token": final_token,
                "status": "Confirmed",
                "amount_wei": final_amount_wei,
                "chain": chain,
                "price_eur": price_eur
                if price_eur is not None
                else (existing.price_eur if existing else None),
                "value_eur": value_eur
                if value_eur is not None
                else (existing.value_eur if existing else None),
                "gas_cost": str(gas_cost)
                if gas_cost is not None
                else (existing.gas_cost if existing else None),
                "gas_value_eur": gas_value_eur
                if gas_value_eur is not None
                else (existing.gas_value_eur if existing else None),
                "tags": json.dumps(merged_tags)
                if merged_tags
                else (existing.tags if existing else None),
            }

            SentTransaction.insert(**data).on_conflict_replace().execute()

    except Exception as e:
        print(f"Failed to log transaction: {e}")
