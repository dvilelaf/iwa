# transfer

Token and native asset transfer services with batch support.

## Files

| File | What | When to read |
|------|------|--------------|
| `base.py` | BaseTransferService - common transfer logic | Transfer abstraction |
| `native.py` | Native asset transfers (ETH, xDAI) | Native transfers |
| `erc20.py` | ERC20 token transfers | Token transfers |
| `multisend.py` | Batch transfers via MultiSend | Batch operations |
| `swap.py` | Token swap transfers | Swap features |
| `__init__.py` | Service factory and exports | Module API |
