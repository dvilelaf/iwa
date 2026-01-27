# Iwa Documentation

*Iwa (岩), meaning "rock" in Japanese, symbolizes the unshakeable stability and immutable foundation required for secure financial infrastructure.*

## Overview

Iwa is a Python framework for secure crypto wallet management designed for building agents and applications that interact with blockchain networks. It provides encrypted key storage, multi-chain support, and a modular plugin system.

## Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/dvilelaf/iwa.git
cd iwa

# Install dependencies
just install
```

### Configuration

Create a `secrets.env` file in the `data/` directory or root:

```bash
WALLET_PASSWORD=your_secure_password
GNOSIS_RPC=https://rpc.gnosis.io
ETHEREUM_RPC=https://mainnet.infura.io/v3/YOUR_KEY
BASE_RPC=https://mainnet.base.org
# ... see full config in Core Modules
```

### Running

```bash
# Launch the Terminal User Interface
just tui

# Launch the Web UI
just web

# Run tests
just test
```

## Documentation Structure

- **[Core Modules](core.md)**: Deep dive into Wallet, KeyStorage, and Chain architecture.
- **[Plugins](plugins/gnosis.md)**: Guides for Gnosis (CowSwap) and Olas integrations.
- **[Interfaces](interfaces/web.md)**: User manuals for Web and CLI.
- **[Development](dev/release.md)**: Contributing guidelines, testing, and release process.

## Key Concepts

### Key Management

Security is paramount. `KeyStorage` is the "vault". It uses a user-provided password to encrypt private keys at rest using AES-GCM with Scrypt key derivation. When needed, keys are decrypted only transiently for signing and then cleared.

**Developer Rule**: Never use `_get_private_key`. Use `sign_transaction` or `sign_message`.

### Plugins

To add a new protocol:

1. Create a directory in `src/iwa/plugins/<protocol_name>`
2. Implement a `Plugin` class inheriting from `iwa.core.plugins.Plugin` in `plugin.py`
3. Define CLI commands in your plugin class
4. Export the plugin class in `__init__.py`

The `PluginLoader` will automatically discover it.

### Chains

Support for new chains can be added in `src/iwa/core/chain.py` by inheriting from `SupportedChain`. Currently supported:

- **Gnosis Chain**: Primary chain with CowSwap integration
- **Ethereum**: Mainnet support
- **Base**: L2 support

## Architecture

```
iwa/
├── core/           # Core wallet functionality
│   ├── keys.py     # KeyStorage - encrypted key management
│   ├── wallet.py   # Wallet - high-level interface
│   ├── chain.py    # ChainInterface - blockchain interaction
│   └── services/   # Service layer (accounts, balances, transactions)
├── plugins/        # Protocol integrations
│   ├── gnosis/     # Safe and CowSwap
│   └── olas/       # Olas Registry and Services
├── tui/            # Terminal User Interface (Textual)
└── web/            # Web API (FastAPI)
```

## API Reference

Run `pydoc` or view source for standard docstrings. Full API documentation is generated via mkdocstrings.
