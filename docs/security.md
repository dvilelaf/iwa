# Security Concept

This document outlines the security architecture of the Iwa Wallet, explaining how secrets, keys, and access controls are managed.

## Overview

Iwa is a self-hosted, local-first wallet management tool. It is designed to be run by a single user or a trusted team on their own infrastructure. No sensitive data is ever sent to external servers controlled by the Iwa developers.

## Secret Management

Application secrets (such as API keys and RPC URLs) are managed via environment variables, typically loaded from a `secrets.env` file.

-   **Loading**: Secrets are loaded into memory using the `Secrets` class (powered by Pydantic settings).
-   **Storage**: The `secrets.env` file should be secured with appropriate file system permissions (e.g., `chmod 600`) to prevent unauthorized access by other users on the system.
-   **Memory**: Once loaded, secrets reside in the application's memory. Debug logs are configured to avoid printing these values, but a memory dump of the running process could reveal them.

## Private Key Management

Private keys are never stored in plain text on the disk.

-   **Keystore**: Encrypted private keys are stored in a JSON keystore file (default: `accounts.json`).
-   **Encryption**: The keystore uses standard encryption (e.g., AES) derived from a user-provided password.
-   **Decryption**: Keys are decrypted **only in memory** and only when needed to sign a transaction.
-   **Session**: When you launch the TUI or CLI, you provide the password. The keys remain accessible in memory for the duration of the session.

## Access Control

Iwa does not implement multi-user roles or permissions.

-   **Single User**: The user running the `iwa` process has full access to all configured wallets.
-   **Infrastructure Security**: Security relies on the security of the host machine (access to the `secrets.env` and `accounts.json` files).

## Logging

To prevent accidental leakage of sensitive information:

-   **File Logging**: Logs are written to `iwa.log`.
-   **Sanitization**: The application is designed to avoid logging private keys or full secret values. However, care should be taken when sharing log files for debugging.
-   **TUI**: The Terminal User Interface suppresses stderr output to prevent logs from overlapping with the UI, redirecting them to the log file instead.

## External Connections

Iwa connects to:

-   **RPC Providers**: configured in `secrets.env` (e.g., Gnosis, Ethereum, Base).
-   **Price APIs**: e.g., Coingecko (if configured).
-   **Etherscan/Gnosisscan**: For fetching ABI or contract details.

Ensure you trust your RPC providers, as they can see your read requests (though they cannot sign transactions for you).
