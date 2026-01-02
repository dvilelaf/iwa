
"""Inspect activity database."""

from iwa.core.db import SentTransaction, db


def inspect_db():
    """Inspect activity database."""
    if db.is_closed():
        db.connect()

    # Get recent transactions (limit 10)
    query = SentTransaction.select().order_by(SentTransaction.timestamp.desc()).limit(10)

    print(f"Found {query.count()} recent transactions:")
    for row in query:
        print(f"TxHash:     {row.tx_hash}")
        print(f"Token:      {row.token}")
        print(f"Amount:     {row.amount_wei}")
        print(f"Tags:       {row.tags}")
        print(f"Gas Cost:   {row.gas_cost}")
        print(f"Value EUR:  {row.value_eur}")
        try:
            if not row.extra_data:
                print("Extra:      None")
            else:
                 print(f"Extra:      {row.extra_data}")
        except Exception:
            print(f"Extra:      {row.extra_data}")
        print("-" * 40)

    if not db.is_closed():
        db.close()

if __name__ == "__main__":
    inspect_db()
