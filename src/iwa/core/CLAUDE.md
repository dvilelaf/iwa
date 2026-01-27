# core

Core wallet functionality: key management, chain interface, and services.

## Directories

| Path | What | When to read |
|------|------|--------------|
| `chain/` | Blockchain interface with rate limiting, RPC rotation | Chain interactions, RPC issues |
| `services/` | Service layer (account, balance, transaction, Safe) | Adding business logic |
| `contracts/` | Contract abstractions (ERC20) | Adding contract support |
| `tests/` | Core unit tests | Adding/modifying tests |

## Files

| File | What | When to read |
|------|------|--------------|
| `keys.py` | KeyStorage - AES-256-GCM encrypted key management | Key security, signing changes |
| `wallet.py` | Wallet - high-level user interface | User-facing wallet features |
| `mnemonic.py` | BIP-39 mnemonic handling | Mnemonic generation/recovery |
| `cli.py` | Typer CLI commands | Adding CLI commands |
| `db.py` | SQLite database (peewee ORM) | Schema changes, data persistence |
| `models.py` | Pydantic models | Adding/modifying data models |
| `settings.py` | Configuration via pydantic-settings | Environment config |
| `plugins.py` | Plugin loading/registration | Plugin system changes |
| `monitor.py` | Transaction monitoring | Monitoring features |
| `pricing.py` | Token price fetching (CoinGecko) | Price display features |
| `ui.py` | Rich console output helpers | CLI formatting |
| `tables.py` | Rich table formatters | Table output |
| `types.py` | Shared type definitions | Type changes |
| `utils.py` | Utility functions | Helper functions |
| `constants.py` | Global constants | Constant values |
| `ipfs.py` | IPFS gateway client | IPFS integration |
