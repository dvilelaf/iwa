# chain

Blockchain interface with rate limiting, RPC rotation, and error handling.

## Files

| File | What | When to read |
|------|------|--------------|
| `interface.py` | ChainInterface - Web3 connection management | Chain interactions, RPC handling |
| `rate_limiter.py` | Token bucket rate limiting with backoff | Rate limit issues, tuning |
| `manager.py` | Multi-chain manager | Multi-chain support |
| `models.py` | Chain config models | Adding chain support |
| `errors.py` | Chain-specific exceptions | Error handling |
| `__init__.py` | Public exports | Module API changes |
