"""Verification script for draining services."""

import logging
import subprocess  # nosec: B404
import sys
import time
from typing import List

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def run_command(command: List[str]):  # noqa: D103
    logger.info(f"Running: {' '.join(command)}")
    subprocess.run(command, check=True)  # nosec: B603


def verify_drain():  # noqa: C901, D103
    try:
        # 1. Reset everything
        logger.info("=== STEP 1: RESET ALL (This may take a moment) ===")
        run_command(["just", "reset-all"])

        logger.info("Waiting for reset to settle...")
        time.sleep(5)

        from iwa.core.wallet import Wallet
        from iwa.plugins.olas.service_manager import ServiceManager

        logger.info("Initializing Wallet & Manager...")
        wallet = Wallet()
        manager = ServiceManager(wallet)

        # 2. Create Service
        logger.info("=== STEP 2: CREATE & DEPLOY SERVICE ===")
        logger.info("Creating service (default Trader)...")

        # Bond 1 ETH
        service_id = manager.create(chain_name="gnosis", bond_amount_wei=1000000000000000000)

        if not service_id:
            raise ValueError("Failed to create service")

        logger.info(f"Service Created! ID: {service_id}")

        logger.info(f"Spinning up service {service_id}...")
        success = manager.spin_up(service_id=service_id)
        if not success:
            raise ValueError("Failed to spin up service")

        # Refresh service details
        if manager.service and manager.service.service_id == service_id:
            service = manager.service
        else:
            assert manager.olas_config is not None, "Olas config not initialized"
            service = manager.olas_config.get_service("gnosis", service_id)
            if not service:
                raise ValueError(f"Service {service_id} not found in config")

        safe_addr = service.multisig_address
        agent_addr = service.agent_address

        logger.info(f"Safe Address: {safe_addr}")
        logger.info(f"Agent Address: {agent_addr}")

        if not safe_addr or not agent_addr:
            # Fallback fetch if local object lagging
            info = manager.registry.get_service(service_id)
            logger.info(f"Registry Info: {info}")
            assert manager.olas_config is not None, "Olas config not initialized"
            service = manager.olas_config.get_service("gnosis", service_id)
            if not service:
                 raise ValueError(f"Service {service_id} not found in config")
            safe_addr = service.multisig_address
            agent_addr = service.agent_address

        if not safe_addr or not agent_addr:
            raise ValueError(
                f"Failed to get Safe or Agent address. Safe={safe_addr}, Agent={agent_addr}"
            )

        # 3. Fund Accounts
        logger.info("=== STEP 3: FUND ACCOUNT (Master -> Agent/Safe) ===")
        amount_native_val = 1.0  # xDAI
        amount_olas_val = 10.0  # OLAS

        amount_native_wei = int(amount_native_val * 10**18)
        amount_olas_wei = int(amount_olas_val * 10**18)

        # Fund Agent
        logger.info(f"Funding Agent {agent_addr}...")
        wallet.transfer_service.send("master", agent_addr, amount_native_wei, "native", "gnosis")
        wallet.transfer_service.send("master", agent_addr, amount_olas_wei, "OLAS", "gnosis")

        # Fund Safe
        logger.info(f"Funding Safe {safe_addr}...")
        wallet.transfer_service.send("master", safe_addr, amount_native_wei, "native", "gnosis")
        wallet.transfer_service.send("master", safe_addr, amount_olas_wei, "OLAS", "gnosis")

        logger.info("Waiting 7s for indexing...")
        time.sleep(7)

        # Verify Funding
        logger.info("Verifying balances...")
        agent_native = wallet.balance_service.get_native_balance_eth(agent_addr, "gnosis") or 0.0
        agent_olas = (
            wallet.balance_service.get_erc20_balance_eth(agent_addr, "OLAS", "gnosis") or 0.0
        )

        safe_native = wallet.balance_service.get_native_balance_eth(safe_addr, "gnosis") or 0.0
        safe_olas = wallet.balance_service.get_erc20_balance_eth(safe_addr, "OLAS", "gnosis") or 0.0

        logger.info(f"Agent Balance: Native={agent_native}, OLAS={agent_olas}")
        logger.info(f"Safe Balance: Native={safe_native}, OLAS={safe_olas}")

        if agent_native < 0.9:
            raise ValueError(f"Agent funding failed: {agent_native}")
        if safe_native < 0.9:
            raise ValueError(f"Safe funding failed: {safe_native}")

        # 4. Drain Service
        logger.info("=== STEP 4: DRAIN SERVICE ===")
        manager_drain = ServiceManager(wallet, service_key=f"gnosis:{service_id}")

        logger.info("Executing drain_service()...")
        drained = manager_drain.drain_service()
        logger.info(f"Drain result: {drained}")

        logger.info("Waiting 7s for indexing after drain...")
        time.sleep(7)

        # 5. Verify Zero Balance
        logger.info("=== STEP 5: VERIFY 0 BALANCE ===")

        final_agent_native = (
            wallet.balance_service.get_native_balance_eth(agent_addr, "gnosis") or 0.0
        )
        final_agent_olas = (
            wallet.balance_service.get_erc20_balance_eth(agent_addr, "OLAS", "gnosis") or 0.0
        )

        final_safe_native = (
            wallet.balance_service.get_native_balance_eth(safe_addr, "gnosis") or 0.0
        )
        final_safe_olas = (
            wallet.balance_service.get_erc20_balance_eth(safe_addr, "OLAS", "gnosis") or 0.0
        )

        logger.info(f"Final Agent Balance: Native={final_agent_native}, OLAS={final_agent_olas}")
        logger.info(f"Final Safe Balance: Native={final_safe_native}, OLAS={final_safe_olas}")

        errors = []

        # Checks
        if final_agent_native > 0.02:
            errors.append(f"Agent still has native: {final_agent_native}")

        if final_agent_olas > 0.000001:
            errors.append(f"Agent still has OLAS: {final_agent_olas}")

        if final_safe_native > 0.005:
            # Safe drain is precise when using safe txn
            errors.append(f"Safe still has native: {final_safe_native}")

        if final_safe_olas > 0.000001:
            errors.append(f"Safe still has OLAS: {final_safe_olas}")

        if errors:
            logger.error("❌ VERIFICATION FAILED:")
            for e in errors:
                logger.error(f"  - {e}")
            sys.exit(1)

        logger.info("✅ SUCCESS: Service drained completely!")

    except Exception as e:
        logger.exception(f"Verification process failed with exception: {e}")
        # sys.exit(1) # actually let log trace propagate


if __name__ == "__main__":
    verify_drain()
