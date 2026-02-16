"""Backfill historical claim rewards from on-chain events.

Queries RewardClaimed events from staking contracts on Gnosis chain
for all configured traders (Jan 2025 → today) and inserts them into
the activity database with CoinGecko EUR pricing.

Uses production Gnosis RPCs directly (not Tenderly) because Tenderly
virtual networks don't store historical event logs.

Usage:
    cd /media/david/DATA/repos/iwa
    uv run python -m iwa.tools.backfill_claims
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger
from web3 import Web3

# Ensure src is in pythonpath
sys.path.append(str(Path(__file__).resolve().parents[2]))

from iwa.core.constants import SECRETS_PATH
from iwa.core.db import init_db, log_transaction
from iwa.core.models import Config
from iwa.core.types import EthereumAddress
from iwa.plugins.olas.models import OlasConfig

# ── Config ──────────────────────────────────────────────────────────
START_TS = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp())
# Gnosis block ~Jan 1, 2025 00:00 UTC (conservative estimate)
START_BLOCK_GNOSIS = 37_700_000
EVENT_CHUNK_SIZE = 50_000

# Staking ABI path
STAKING_ABI_PATH = Path(__file__).resolve().parents[1] / "plugins" / "olas" / "contracts" / "abis" / "staking.json"

# Production Gnosis RPCs — used with rotation for rate limit resilience
GNOSIS_RPCS = [
    "https://rpc.gnosischain.com",
    "https://rpc.gnosis.gateway.fm",
    "https://gnosis-rpc.publicnode.com",
    "https://gnosis.drpc.org",
    "https://1rpc.io/gnosis",
    "https://0xrpc.io/gno",
]


def get_web3_instances() -> list[Web3]:
    """Connect to multiple Gnosis RPCs for rotation."""
    instances = []
    for rpc in GNOSIS_RPCS:
        try:
            w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 30}))
            if w3.is_connected():
                instances.append(w3)
                logger.info(f"Connected to {rpc}")
        except Exception:
            continue
    if not instances:
        logger.error("Failed to connect to any Gnosis RPC")
        sys.exit(1)
    return instances


def load_staking_abi() -> list:
    """Load the staking contract ABI."""
    with open(STAKING_ABI_PATH) as f:
        return json.load(f)


def load_traders() -> tuple[dict, set]:
    """Load traders from config.yaml."""
    config = Config()
    raw = config.plugins.get("olas")
    if not raw:
        logger.error("No OLAS plugin config found")
        sys.exit(1)
    olas_config = OlasConfig.model_validate(raw)

    service_id_map = {}
    staking_contracts = set()

    for _key, svc in olas_config.services.items():
        service_id_map[svc.service_id] = svc
        if svc.staking_contract_address:
            staking_contracts.add(str(svc.staking_contract_address))

    logger.info(f"Loaded {len(service_id_map)} traders, {len(staking_contracts)} unique staking contracts")
    return service_id_map, staking_contracts


def fetch_events_chunked(contract, event_name: str, from_block: int, to_block: int, chunk_size: int) -> list:
    """Fetch events in chunks to handle RPC block range limits."""
    all_logs = []
    event = getattr(contract.events, event_name)
    current_from = from_block

    while current_from <= to_block:
        current_to = min(current_from + chunk_size - 1, to_block)
        for attempt in range(5):
            try:
                logs = event.get_logs(from_block=current_from, to_block=current_to)
                all_logs.extend(logs)
                current_from = current_to + 1
                break
            except Exception as e:
                error_msg = str(e).lower()
                # Block range too large → halve and recurse
                if ("range" in error_msg or "limit" in error_msg or "10000" in error_msg) and chunk_size > 500:
                    logger.debug(f"Block range too large ({chunk_size}), halving...")
                    half_logs = fetch_events_chunked(contract, event_name, current_from, current_to, chunk_size // 2)
                    all_logs.extend(half_logs)
                    current_from = current_to + 1
                    break
                # Rate limit or transient error → retry with backoff
                if attempt < 4:
                    wait = min(2 ** attempt, 16)
                    logger.debug(f"Retry {attempt + 1}/5 for {event_name} ({current_from}-{current_to}), waiting {wait}s: {e}")
                    time.sleep(wait)
                else:
                    logger.error(f"FAILED after 5 attempts for {event_name} ({current_from}-{current_to}): {e}")
                    current_from = current_to + 1

    return all_logs


def fetch_historical_prices() -> dict[str, float]:
    """Fetch OLAS/EUR daily prices from DeFiLlama (free, no API key).

    Uses the /chart endpoint for OLAS on Gnosis chain with daily granularity.
    Converts USD prices to EUR using a separate EUR/USD rate.
    """
    import requests

    # OLAS token on Gnosis chain
    olas_id = "gnosis:0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f"

    # Fetch OLAS/USD daily chart from DeFiLlama
    url = f"https://coins.llama.fi/chart/{olas_id}?start={START_TS}&span=500&period=1d"
    logger.info("Fetching OLAS/USD prices from DeFiLlama...")
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    coins_data = data.get("coins", {}).get(olas_id, {})
    prices_list = coins_data.get("prices", [])

    if not prices_list:
        logger.error(f"No price data from DeFiLlama. Response: {data}")
        sys.exit(1)

    # Get current EUR/USD rate for conversion
    # DeFiLlama returns EURT price in USD (e.g., 1 EURT = $1.08)
    # To convert USD → EUR: usd_to_eur = 1 / eur_price
    # Valid range: 0.8 - 1.2 (sanity check for API errors)
    eur_url = "https://coins.llama.fi/prices/current/coingecko:tether-eurt"
    usd_to_eur = 0.92  # Fallback: approximate rate

    try:
        eur_resp = requests.get(eur_url, timeout=10)
        if eur_resp.ok:
            eur_data = eur_resp.json()
            eur_price = eur_data.get("coins", {}).get("coingecko:tether-eurt", {}).get("price")

            if eur_price and eur_price > 0:
                calculated_rate = 1.0 / eur_price

                # Sanity check: USD/EUR should be ~0.8-1.2
                if 0.8 <= calculated_rate <= 1.2:
                    usd_to_eur = calculated_rate
                    logger.info(f"Using DeFiLlama USD/EUR rate: {usd_to_eur:.4f} (EURT price: ${eur_price:.4f})")
                else:
                    logger.warning(f"Invalid USD/EUR rate {calculated_rate:.4f} from EURT=${eur_price:.4f}, using fallback {usd_to_eur}")
            else:
                logger.warning(f"No valid EURT price in API response, using fallback rate {usd_to_eur}")
    except Exception as e:
        logger.warning(f"Failed to fetch EUR rate from DeFiLlama: {e}, using fallback {usd_to_eur}")

    logger.info(f"Final USD/EUR conversion rate: {usd_to_eur:.4f}")

    date_prices = {}
    for entry in prices_list:
        ts = entry.get("timestamp", 0)
        usd_price = entry.get("price", 0)
        date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        date_prices[date_str] = usd_price * usd_to_eur

    logger.info(f"Fetched {len(date_prices)} daily OLAS/EUR prices from DeFiLlama")
    return date_prices


def get_block_timestamps(web3_list: list[Web3], block_numbers: set[int]) -> dict[int, datetime]:
    """Fetch timestamps for block numbers, rotating across RPCs to avoid rate limits."""
    cache = {}
    total = len(block_numbers)
    rpc_count = len(web3_list)
    sorted_blocks = sorted(block_numbers)

    for i, block_num in enumerate(sorted_blocks):
        # Rotate across RPCs
        w3 = web3_list[i % rpc_count]
        for attempt in range(5):
            try:
                block = w3.eth.get_block(block_num)
                cache[block_num] = datetime.fromtimestamp(block.timestamp, tz=timezone.utc)
                break
            except Exception as e:
                if attempt < 4:
                    # Try a different RPC on retry
                    w3 = web3_list[(i + attempt + 1) % rpc_count]
                    wait = min(2 ** attempt, 8)
                    time.sleep(wait)
                else:
                    logger.error(f"Failed to get block {block_num} after 5 attempts: {e}")
                    raise
        if (i + 1) % 100 == 0:
            logger.info(f"  Block timestamps: {i + 1}/{total}")

    logger.info(f"Fetched {total} block timestamps")
    return cache


def main() -> None:
    """Run the backfill."""
    if SECRETS_PATH.exists():
        load_dotenv(SECRETS_PATH, override=True)

    # Ensure DB tables exist
    init_db()

    service_id_map, staking_contracts = load_traders()

    # ── Step 1: Connect to production Gnosis RPCs ───────────────────
    web3_list = get_web3_instances()
    web3 = web3_list[0]  # Primary for events
    abi = load_staking_abi()

    latest_block = web3.eth.block_number
    start_block = START_BLOCK_GNOSIS
    logger.info(f"Block range: {start_block} → {latest_block} ({latest_block - start_block} blocks)")

    # ── Step 2: Fetch RewardClaimed events ──────────────────────────
    all_events = []
    for addr in sorted(staking_contracts):
        logger.info(f"Querying RewardClaimed from {addr}...")
        contract = web3.eth.contract(address=EthereumAddress(addr), abi=abi)
        events = fetch_events_chunked(contract, "RewardClaimed", start_block, latest_block, EVENT_CHUNK_SIZE)

        our_events = [(addr, ev) for ev in events if ev.args.serviceId in service_id_map]
        logger.info(f"  Found {len(events)} total events, {len(our_events)} for our traders")
        all_events.extend(our_events)

    logger.info(f"Total events to process: {len(all_events)}")

    if not all_events:
        logger.warning("No events found. Nothing to backfill.")
        return

    # ── Step 3: Get block timestamps (rotate across RPCs) ───────────
    unique_blocks = {ev.blockNumber for _, ev in all_events}
    block_ts = get_block_timestamps(web3_list, unique_blocks)

    # ── Step 4: Fetch historical prices ─────────────────────────────
    date_prices = fetch_historical_prices()

    # ── Step 5: Insert into DB ──────────────────────────────────────
    inserted = 0
    skipped = 0

    for staking_addr, ev in all_events:
        service_id = ev.args.serviceId
        reward = ev.args.reward
        tx_hash = ev.transactionHash.hex()
        block_num = ev.blockNumber

        svc = service_id_map[service_id]
        ts = block_ts[block_num].replace(tzinfo=None)  # naive UTC for peewee
        date_str = ts.strftime("%Y-%m-%d")
        price = date_prices.get(date_str)

        olas_amount = reward / 1e18
        value_eur = olas_amount * price if price else None

        if reward == 0:
            skipped += 1
            continue

        log_transaction(
            tx_hash=tx_hash,
            from_addr=staking_addr,
            to_addr=str(svc.multisig_address),
            token="OLAS",
            amount_wei=str(reward),
            chain="gnosis",
            from_tag="staking_contract",
            to_tag=svc.service_name,
            price_eur=price,
            value_eur=value_eur,
            tags=["olas_claim_rewards", "staking_reward"],
            timestamp=ts,
        )
        inserted += 1

    logger.info(f"Done! Inserted {inserted} claims, skipped {skipped} zero-reward events.")


if __name__ == "__main__":
    main()
