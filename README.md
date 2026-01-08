# Iwa

[![PyPI version](https://badge.fury.io/py/iwa.svg)](https://badge.fury.io/py/iwa)
[![Docker Pulls](https://img.shields.io/docker/pulls/dvilela/iwa.svg)](https://hub.docker.com/r/dvilela/iwa)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-672%20passed-brightgreen.svg)]()
[![Coverage](https://img.shields.io/badge/coverage-86%25-brightgreen.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

*Iwa (岩), meaning "rock" in Japanese, symbolizes the unshakeable stability and immutable foundation required for secure financial infrastructure.*

</br>
<p align="center">
  <img width="40%" src="https://raw.githubusercontent.com/dvilelaf/iwa/master/images/iwa.png">
</p>
</br>

Iwa is a Python framework designed for managing crypto wallets and interacting with smart contracts and crypto protocols in a secure, modular, and extensible way. It's ideal for building autonomous agents and applications that require blockchain interactions.

## Features

- **Secure Key Storage**: Private keys are encrypted with AES-256-GCM and stored safely. They are never exposed to the application layer; signing happens internally via the `KeyStorage` class.

- **Modularity (Plugins)**: Protocols and features are implemented as plugins, loaded dynamically. Currently supports Gnosis (Safe, CowSwap) and Olas (Registry, Services, Staking).

- **Multi-Chain Support**: Native support for Gnosis Chain, Ethereum, and Base, with easy extensibility for others.

- **Robust Transaction Management**:
  - **RPC Rotation**: Automatically switches RPC providers if one fails or is rate-limited.
  - **Rate Limiting**: Token bucket algorithm with automatic backoff.
  - **Retry Logic**: Automatic retries with exponential backoff for transient failures.

- **CLI & TUI Integration**: Interact with your wallet via a unified CLI or a beautiful Terminal User Interface built with Textual.

- **Web API**: RESTful API built with FastAPI for web-based integrations.

- **Modern Tooling**: Managed with `uv`, `Justfile` for automation, and ready for Docker deployment.

## Architecture

```
iwa/
├── core/               # Core wallet functionality
│   ├── keys.py         # KeyStorage - Encrypted key management
│   ├── wallet.py       # Wallet - High-level interface
│   ├── chain.py        # ChainInterface - Blockchain interaction with rate limiting
│   ├── services/       # Service layer (accounts, balances, transactions)
│   └── contracts/      # Contract abstractions (ERC20, Safe)
├── plugins/            # Protocol integrations
│   ├── gnosis/         # Safe multisig and CowSwap DEX
│   └── olas/           # Olas Registry, Services, Staking
├── tui/                # Terminal User Interface (Textual)
└── web/                # Web API (FastAPI)
```

### Key Components

| Component | Description |
|-----------|-------------|
| `KeyStorage` | Encrypts/decrypts private keys, provides internal signing |
| `Wallet` | Main high-level interface for user interactions |
| `ChainInterface` | Manages Web3 connections with rate limiting and RPC rotation |
| `TransactionService` | Handles transaction signing and sending with retry logic |
| `PluginService` | Dynamically loads and manages protocol plugins |

## Setup & Usage

### Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) package manager

### Installation

```bash
# Install from PyPI
pip install iwa

# Or using uv (recommended for tools)
uv tool install iwa

# Or from source
git clone https://github.com/dvilelaf/iwa.git
cd iwa
just install
```

### Configuration

Create a `secrets.env` file with your configuration:

```bash
WALLET_PASSWORD=your_secure_password
GNOSIS_RPC=https://rpc.gnosis.io,https://gnosis.drpc.org
ETHEREUM_RPC=https://mainnet.infura.io/v3/YOUR_KEY
BASE_RPC=https://mainnet.base.org

# Optional
GNOSISSCAN_API_KEY=your_api_key
COINGECKO_API_KEY=your_api_key
```

### Running

```bash
# Launch TUI
just tui

# Launch Web UI
just web

# Use CLI
iwa wallet list --chain gnosis
iwa wallet balance <address> --chain gnosis
```

### Running Tests

```bash
just test
```

### Security Checks

```bash
just security  # Runs gitleaks, bandit, and pip-audit
```

### Docker

```bash
# Pull from Docker Hub
docker pull dvilelaf/iwa:latest

# Build locally
just docker-build
just docker-run
```

## Plugins

Plugins are located in `src/iwa/plugins`. Currently supported:

### Gnosis Plugin
- **Safe**: Create and manage Safe multisig wallets
- **CowSwap**: Token swaps via CoW Protocol with MEV protection, Max balance support, and auto-refreshing UI

### Olas Plugin
- **Registry**: Interact with Olas service registry
- **Services**: Create, deploy, and manage Olas services
- **Staking**: Stake/unstake services and claim rewards

## Transaction Flow

1. **Preparation**: A high-level method prepares a raw transaction dictionary
2. **Delegation**: The transaction is passed to `TransactionService`
3. **Signing**: `KeyStorage` decrypts the key in memory, signs, and wipes the key
4. **Sending**: The signed transaction is sent via `ChainInterface`
5. **Recovery**: Automatic RPC rotation and gas bumping on failures
6. **Receipt**: Transaction receipt is returned upon success

## Documentation

Full documentation is available in the `docs/` directory:

```bash
# Serve docs locally
just docs-serve

# Build static docs
just docs-build
```

## Development

```bash
# Format code
just format

# Lint code
just check

# Type check
just types
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.