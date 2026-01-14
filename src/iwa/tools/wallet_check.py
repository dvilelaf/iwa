"""Wallet integrity check utility."""

import sys

from eth_account import Account

from iwa.core.keys import KeyStorage
from iwa.core.mnemonic import EncryptedMnemonic
from iwa.core.models import StoredSafeAccount
from iwa.core.secrets import secrets
from iwa.core.utils import configure_logger

# Configure logger to be quiet for this tool unless error
logger = configure_logger()


def _check_accounts(storage: KeyStorage) -> bool:
    """Verify that all EOAs in the wallet can be decrypted.

    Args:
        storage: The KeyStorage instance.

    Returns:
        bool: True if all EOAs were verified successfully.

    """
    if not storage.accounts:
        print("⚠️  No accounts found in wallet.json.")
        return True

    success_count = 0
    fail_count = 0
    safe_count = 0

    # Ensure we sort by tag for consistent output
    sorted_accounts = sorted(storage.accounts.values(), key=lambda x: x.tag if x.tag else "")

    for account in sorted_accounts:
        if isinstance(account, StoredSafeAccount):
            print(
                f"🔹 [Safe]  {account.address} (tag: {account.tag or 'none'}) "
                "- Skipped (Contract Wallet)"
            )
            safe_count += 1
            continue

        try:
            # Decrypt using the password from secrets.env
            priv_key = account.decrypt_private_key()

            # Verify address matches
            derived_acct = Account.from_key(priv_key)

            if derived_acct.address.lower() == account.address.lower():
                print(f"✅ [EOA]   {account.address} (tag: {account.tag or 'none'}) - OK")
                success_count += 1
            else:
                print(
                    f"❌ [EOA]   {account.address} (tag: {account.tag or 'none'}) "
                    "- ADDRESS MISMATCH!"
                )
                print(f"    Expected: {account.address}")
                print(f"    Derived:  {derived_acct.address}")
                fail_count += 1
        except Exception as e:
            print(
                f"❌ [EOA]   {account.address} (tag: {account.tag or 'none'}) - DECRYPTION FAILED!"
            )
            print(f"    Error: {e}")
            fail_count += 1

    print("\n" + "-" * 40)
    print(f"Accounts Verified: {success_count}")
    print(f"Accounts Failed:   {fail_count}")
    if safe_count:
        print(f"Safes Skipped:     {safe_count}")

    return fail_count == 0


def _check_mnemonic(storage: KeyStorage) -> bool:
    """Verify that the encrypted mnemonic can be decrypted.

    Args:
        storage: The KeyStorage instance.

    Returns:
        bool: True if the mnemonic was verified successfully.

    """
    print("\n🔍 Checking Mnemonic...")
    if not storage.encrypted_mnemonic:
        print("⚠️  No encrypted mnemonic found in wallet.json.")
        return True

    try:
        # Instantiate EncryptedMnemonic from the dict stored in KeyStorage
        enc_mnemonic = EncryptedMnemonic(**storage.encrypted_mnemonic)

        # Get password (checked implicitly by KeyStorage init)
        password = secrets.wallet_password.get_secret_value()

        # Attempt decryption
        mnemonic_text = enc_mnemonic.decrypt(password)

        if mnemonic_text:
            # Basic validation (e.g. check word count) - explicit
            word_count = len(mnemonic_text.split())
            if word_count in [12, 15, 18, 21, 24]:
                print(f"✅ [Mnemonic] Decryption successful ({word_count} words).")
                return True
            print(f"⚠️  [Mnemonic] Decryption successful but unusual word count: {word_count}")
            return True

        print("❌ [Mnemonic] Decrypted to empty string.")
        return False

    except Exception as e:
        print(f"❌ [Mnemonic] Decryption FAILED! Error: {e}")
        return False


def check_wallet() -> None:
    """Verify that all EOAs in the wallet can be decrypted and mnemonic is valid."""
    print("🔍 Verifying wallet integrity...")
    print("This process checks if the WALLET_PASSWORD in secrets.env can decrypt all accounts.")
    print()

    try:
        # KeyStorage loads WALLET_PATH and uses secrets.wallet_password by default
        storage = KeyStorage()
    except Exception as e:
        print(f"❌ Critical Error: Could not initialize KeyStorage. {e}")
        sys.exit(1)

    accounts_ok = _check_accounts(storage)
    mnemonic_ok = _check_mnemonic(storage)

    print("\n" + "=" * 40)
    print("REPORT SUMMARY")
    if accounts_ok and mnemonic_ok:
        print("✨ All checks passed! Wallet is healthy.")
        sys.exit(0)
    else:
        print("❌ Wallet check FAILED. See errors above.")
        sys.exit(1)


if __name__ == "__main__":
    check_wallet()
