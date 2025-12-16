"""Database models and utilities."""

from datetime import datetime
from pathlib import Path

from peewee import (
    CharField,
    DateTimeField,
    FloatField,
    Model,
    SqliteDatabase,
)

from iwa.core.constants import WALLET_PATH

# Determine DB path (sibling to wallet.json)
# Assuming WALLET_PATH is like ~/.iwa/wallet.json
# DB will be ~/.iwa/activity.db
DB_PATH = Path(WALLET_PATH).parent / "activity.db"

db = SqliteDatabase(str(DB_PATH))


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
    token_symbol = CharField(null=True)
    amount_wei = CharField()  # Store as string to avoid precision loss
    chain = CharField()
    timestamp = DateTimeField(default=datetime.now)
    # Pricing info
    price_eur = FloatField(null=True)
    value_eur = FloatField(null=True)
    gas_cost = CharField(null=True)  # Wei
    gas_value_eur = FloatField(null=True)


def init_db():
    """Initialize the database."""
    db.connect()
    db.create_tables([SentTransaction], safe=True)

    # Simple migration: check if columns exist, if not add them
    # This prevents errors if the DB was already created without these columns
    columns = [c.name for c in db.get_columns("senttransaction")]
    if "from_tag" not in columns:
        try:
            from playhouse.migrate import SqliteMigrator, migrate

            migrator = SqliteMigrator(db)
            migrate(
                migrator.add_column("senttransaction", "from_tag", CharField(null=True)),
                migrator.add_column("senttransaction", "to_tag", CharField(null=True)),
                migrator.add_column("senttransaction", "token_symbol", CharField(null=True)),
            )
        except Exception as e:
            print(f"Migration failed: {e}")

    if "price_eur" not in columns:
        try:
            # Re-init migrator if needed or reuse
            if "migrator" not in locals():
                from playhouse.migrate import SqliteMigrator, migrate

                migrator = SqliteMigrator(db)
            if "migrate" not in locals():
                from playhouse.migrate import migrate

            migrate(
                migrator.add_column("senttransaction", "price_eur", FloatField(null=True)),
                migrator.add_column("senttransaction", "value_eur", FloatField(null=True)),
                migrator.add_column("senttransaction", "gas_cost", CharField(null=True)),
                migrator.add_column("senttransaction", "gas_value_eur", FloatField(null=True)),
            )
        except Exception as e:
            print(f"Migration (pricing) failed: {e}")

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
    token_symbol=None,
    price_eur=None,
    value_eur=None,
    gas_cost=None,
    gas_value_eur=None,
):
    try:
        with db:
            SentTransaction.create(
                tx_hash=tx_hash,
                from_address=from_addr,
                from_tag=from_tag,
                to_address=to_addr,
                to_tag=to_tag,
                token=token,
                token_symbol=token_symbol,
                amount_wei=str(amount_wei),
                chain=chain,
                price_eur=price_eur,
                value_eur=value_eur,
                gas_cost=gas_cost,
                gas_value_eur=gas_value_eur,
            )
    except Exception as e:
        print(f"Failed to log transaction: {e}")
