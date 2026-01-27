# services

Service layer providing business logic for wallet operations.

## Directories

| Path | What | When to read |
|------|------|--------------|
| `transfer/` | Token transfer service | Transfer feature work |

## Files

| File | What | When to read |
|------|------|--------------|
| `transaction.py` | TransactionService - signing, sending, retry logic | Transaction handling |
| `safe.py` | SafeService - Safe multisig operations | Safe wallet features |
| `balance.py` | BalanceService - token balance queries | Balance display |
| `account.py` | AccountService - account management | Account operations |
| `plugin.py` | PluginService - dynamic plugin loading | Plugin management |
| `__init__.py` | Service exports | Module API |
