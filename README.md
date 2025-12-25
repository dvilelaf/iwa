# Iwa - Secure Crypto Wallet Framework

Iwa is a Python framework designed for managing crypto wallets and interacting with smart contracts and crypto protocols in a secure, modular, and extensible way.

## Features

- **Secure Key Storage**: Private keys are encrypted and stored safely. They are ideally never exposed to the application layer, with signing happening internally.
- **Modularity (Plugins)**: Protocols and features are implemented as plugins, loaded dynamically.
- **Multi-Chain Support**: Native support for Gnosis Chain, Ethereum, and Base, with easy extensibility for others.
- **Robust Transaction Management**:
  - **RPC Rotation**: Automatically switches RPC providers if one fails or is rate-limited.
  - **Automatic Gas Management**: Retries transactions with increased gas prices upon failure.
  - **Internal Signing**: Transactions are signed within the secure `KeyStorage` module.
- **CLI & TUI Integration**: Interact with your wallet via a unified CLI or a Terminal User Interface.
- **Modern Tooling**: Managed with `uv`, `Justfile` for automation, and ready for Docker deployment.

## Architecture & Important Classes

### `KeyStorage` (`iwa.core.keys`)
The heart of the security model. It stores encrypted private keys (`EncryptedAccount`) and manages Safe multisig accounts (`StoredSafeAccount`).
- **Internal Signing**: Methods like `sign_transaction` and `sign_message` handle cryptographic operations without returning the raw private key to the caller.
- **Encryption**: Uses AES-GCM for encryption and Scrypt for key derivation.

### `Wallet` (`iwa.core.wallet`)
The main high-level interface for user interactions.
- Delegated signing to `KeyStorage`.
- Orchestrates complex flows like swaps, transfers, and multisig interactions.

### `TransactionManager` (`iwa.core.managers`)
Handles the low-level details of sending transactions.
- **Retry Logic**: Implements retries for gas issues and connection failures.
- **RPC Rotation**: Automatically rotates through configured RPCs in case of errors.

### `ChainInterface` (`iwa.core.chain`)
Abstraction layer for blockchain interactions via Web3.
- Manages connection to RPC nodes.
- Provides helper methods for balance checks, contract interaction, etc.

### Web API (`iwa.web`)
Modular Web API built with FastAPI.
- **Routers**: Split into `accounts`, `transactions`, `olas`, `swap`, and `state` for modularity.
- **Dependencies**: Centralized dependency injection for authentication and wallet access.

### TUI (`iwa.tui`)
Terminal User Interface built with Textual.
- **Screens**: Dedicated screens for Wallet management (`WalletsScreen`).
- **Widgets**: Reusable components like `AccountTable` and `ChainSelector` in `iwa.tui.widgets`.
- **Workers**: Background workers for fetching balances (`fetch_all_balances`) and monitoring events.

## Transaction Flow

1. **Preparation**: A high-level method (e.g., in `Wallet` or a Plugin) calls a contract wrapper to prepare a raw transaction dictionary (data, to, value, etc.).
2. **Delegation**: The transaction is passed to `TransactionManager` (via `Wallet.sign_and_send_transaction`).
3. **Signing**: `TransactionManager` requests `KeyStorage` to sign the transaction. `KeyStorage` decrypts the key in memory, signs, and wipes the key (best effort).
4. **Sending**: `TransactionManager` sends the signed transaction via `ChainInterface`.
5. **Monitoring & Recovery**:
   - If the RPC fails, `TransactionManager` triggers `ChainInterface.rotate_rpc()` and retries.
   - If the transaction fails due to low gas, it bumps the gas price and retries.
6. **Receipt**: Upon success, the transaction receipt is returned.

## Setup & Usage

### Prerequisites
- Python 3.12+
- `uv` package manager

### Installation
```bash
just install
```

### Configuration
Create a `secrets.env` file (see `src/iwa/core/models.py` for schema) or set environment variables for RPCs and wallet password.
Example `secrets.env`:
```
WALLET_PASSWORD=your_secure_password
GNOSIS_RPC=https://rpc.gnosis.io
ETHEREUM_RPC=https://mainnet.infura.io/v3/YOUR_KEY
BASE_RPC=https://mainnet.base.org
```

### Running Tests
```bash
just test
```

### Running CLI
```bash
just run wallet list --chain gnosis
```

### Running TUI
```bash
just run tui
```

### Docker
```bash
just docker-build
just docker-run
```

## Plugins
Plugins are located in `src/iwa/plugins`. Currently supported:
- **Gnosis**: Helpers for Safe and CowSwap.
- **Olas**: Interaction with Olas registry and services.


## Documentation
Full documentation is available in the `docs/` directory and can be served locally:
```bash
mkdocs serve
```
Or built statically:
```bash
mkdocs build
```