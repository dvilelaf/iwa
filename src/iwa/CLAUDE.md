# iwa

Main package entry point with CLI and module bootstrapping.

## Directories

| Path | What | When to read |
|------|------|--------------|
| `core/` | Core wallet functionality, keys, chain interface | Core feature work, security changes |
| `plugins/` | Protocol integrations (Gnosis, Olas) | Adding/modifying protocol support |
| `tui/` | Terminal UI (Textual) | TUI feature work |
| `web/` | Web API (FastAPI) | Web API feature work |
| `tools/` | CLI dev utilities | Adding dev scripts |

## Files

| File | What | When to read |
|------|------|--------------|
| `__init__.py` | Package version | Checking version |
| `__main__.py` | Module entry point | Modifying CLI bootstrap |
