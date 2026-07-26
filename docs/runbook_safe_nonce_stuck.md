# Runbook: Safe Nonce Stuck

## Symptoms

- `safe_nonce_stuck` ERROR in logs:
  ```
  safe_nonce_stuck: Safe 0xbEC49fa1 chain=gnosis nonce has not advanced for 180s
  with 3 pending deliveries — possible stuck TX.
  ```
- `safe_eoa_gap` ERROR in logs:
  ```
  safe_eoa_gap: Safe 0xbEC49fa1 chain=gnosis EOA confirmed=42 pending=46 gap=4
  > threshold=3 — blocking allocator until gap resolves.
  ```
- `NonceAllocatorBlocked` exceptions in micromech delivery logs.
- Deliveries stalling; requests accumulating in EXECUTED state.

## Diagnosis

### 1. Check current nonce state

```bash
iwa gnosis nonce-check <SAFE_ADDRESS> --chain gnosis
```

Output example:
```
Safe nonce (on-chain):      42
EOA signer confirmed nonce: 10
EOA signer pending nonce:   14
EOA mempool gap:            4
WARNING: gap 4 > 3 — possible stuck TX in mempool.
```

### 2. Find the stuck TX

Use the signer EOA address from the wallet to inspect the mempool:

```bash
# Get signer address from wallet
iwa wallet list

# Check pending TXs on-chain explorer (Gnosisscan)
# Look for pending TXs from the signer EOA
# The stuck TX will have the lowest pending nonce (e.g. nonce=10)
```

### 3. Identify the cause

Common causes:
- **Gas price too low**: TX was submitted with insufficient gas during a spike.
- **Nonce skip**: A TX was submitted with nonce=N but nonce=N-1 is still pending.
- **RPC inconsistency**: One RPC reported success but another still sees it pending.

## Resolution

### Option A: Speed-up / Replace stuck TX

If the stuck TX has insufficient gas, replace it with a higher-gas version:

```bash
# From Blockscout: find stuck TX hash, then replace with higher gas via Safe UI
# or submit a replacement TX at the same nonce with higher gas price
```

### Option B: Send a noop TX (advance nonce)

If the stuck TX can be safely dropped (zero-value self-transfer to replace it):

> **WARNING**: Run this only when the micromech process is stopped, or when you are certain no
> other process is using the NonceAllocator for this Safe. Concurrent use can cause nonce
> collisions. To stop micromech: `ssh triton "cd /opt/micromech && docker compose stop micromech"`

```bash
iwa gnosis send-noop <SAFE_ADDRESS> --chain gnosis
```

This submits a zero-value Safe TX to the Safe itself, advancing the Safe nonce
by 1. Useful when the Safe nonce is stuck due to a dropped TX.

### Option C: Manual allocator invalidation (process restart)

If the running micromech process has a stale allocator state:

```bash
# The CLI creates a new SafeService instance, not the running process's allocator.
# To invalidate the running process's allocator, restart micromech:
ssh triton "cd /opt/micromech && just update"
```

After restart, the NonceAllocator refetches the on-chain nonce on the next
delivery tick.

### Option D: Disable parallel dispatch (emergency fallback)

If the nonce system is repeatedly degraded and the above options are insufficient,
disable parallel dispatch to revert to the safe serial path:

```bash
# 1. Edit micromech config on the server
ssh triton "nano /opt/micromech/data/config.yaml"
# Set: parallel_nonce_enabled: false

# 2. Restart micromech to apply the change
ssh triton "cd /opt/micromech && just update"

# 3. Verify serial mode active — deliveries resume but throughput drops to ~4/min
ssh triton "docker compose logs -f micromech 2>&1 | grep 'NonceAllocator'"
# Should NOT see "NonceAllocator(...) allocated nonce" lines
```

Re-enable parallel dispatch once the root cause is resolved.

### Troubleshooting: if `send-noop` itself is stuck

If `send-noop` hangs or the resulting TX is also dropped:

1. **Check gas price**: the Safe TX Service may be submitting with too low a gas
   price. Check Gnosisscan for the pending TX and replace it manually with a
   higher gas price via the Safe UI.

2. **Check wallet balance**: the signer EOA must have enough xDAI to pay gas.
   `iwa wallet balance <signer_address> --chain gnosis`

3. **Check Safe TX Service availability**: `https://safe-transaction-gnosis.safe.global/`
   — if it's down, no Safe TXs can be submitted.

4. **Last resort**: if the Safe TX Service queue is stuck with an undroppable TX,
   contact Safe support or wait for the mempool to clear.

## Recovery Verification

After resolving the stuck TX, confirm recovery:

1. Monitor micromech logs for `NonceAllocator invalidated` message.
2. Confirm deliveries resume (look for "Delivered" log lines).
3. Run `iwa gnosis nonce-check` again to verify gap = 0.

## Prevention

- `nonce_gap_alert_threshold: 3` in `data/config.yaml` (micromech) raises an
  alert before the gap becomes critical.
- `parallel_nonce_enabled: true` distributes nonce usage across workers, making
  individual TX failures less likely to block the entire queue.
- Monitor `safe_nonce_stuck` alerts in production (forwarded to Telegram via
  micromech notification service when alert threshold fires).

## Related Configuration

```yaml
# data/config.yaml (micromech section)
micromech:
  nonce_gap_alert_threshold: 3    # alert + block allocator when EOA gap > 3
  parallel_nonce_enabled: true    # enable NonceAllocator parallel dispatch
```

## Related Code

- `iwa/src/iwa/core/services/safe.py` — `NonceAllocator`, `NonceAllocatorBlocked`
- `micromech/src/micromech/runtime/delivery.py` — `_deliver_concurrent`, `_dispatch`
- `iwa/src/iwa/plugins/gnosis/plugin.py` — `send-noop`, `nonce-check` CLI commands
