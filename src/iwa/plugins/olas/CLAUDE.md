# olas

Olas protocol integration: Registry, Services, and Staking.

## Directories

| Path | What | When to read |
|------|------|--------------|
| `service_manager/` | Service lifecycle management | Service operations |
| `contracts/` | Olas contract wrappers | Contract interactions |
| `tui/` | Olas-specific TUI components | Olas UI features |
| `scripts/` | Integration test scripts | Testing Olas features |
| `tests/` | Plugin tests | Adding/modifying tests |

## Files

| File | What | When to read |
|------|------|--------------|
| `plugin.py` | OlasPlugin registration and commands | Plugin setup |
| `importer.py` | Service import from Olas registry | Importing services |
| `constants.py` | Olas contract addresses, chain config | Chain-specific constants |
| `models.py` | Olas-specific data models | Data structures |
| `mech_reference.py` | Mech reference implementation | Mech integration |
| `__init__.py` | Plugin exports | Module API |
