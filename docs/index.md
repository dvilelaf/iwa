# Documentation

## Overview
Iwa is designed to be the foundation for secure python-based crypto agents and applications.

## Key Concepts

### Key Management
Security is paramount. `KeyStorage` is the "vault". It uses a user-provided password to encrypt private keys at rest. When needed, keys are decrypted only transiently for signing and then cleared.
**Developer Rule**: Never use `_get_private_key`. Use `sign_transaction` or `sign_message`.

### Plugins
To add a new protocol:
1. Create a directory in `src/iwa/plugins/<protocol_name>`.
2. Implement a `Plugin` class inheriting from `iwa.core.plugins.Plugin` in `plugin.py`.
3. Define CLI commands in your plugin class.
4. Export the plugin class in `__init__.py`.
The `PluginLoader` will automatically discover it.

### Chains
Support for new chains can be added in `src/iwa/core/chain.py` by inheriting from `SupportedChain`.

## API Reference
(Run `pydoc` or view source for standard docstrings)
