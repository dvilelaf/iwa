"""ServiceManager base class."""

from typing import Dict, Optional

from loguru import logger

from iwa.core.chain import ChainInterfaces
from iwa.core.models import Config
from iwa.core.wallet import Wallet
from iwa.plugins.olas.constants import OLAS_CONTRACTS
from iwa.plugins.olas.contracts.service import ServiceManagerContract, ServiceRegistryContract
from iwa.plugins.olas.models import OlasConfig


class ServiceManagerBase:
    """Base class for ServiceManager."""

    def __init__(self, wallet: Wallet, service_key: Optional[str] = None):
        """Initialize ServiceManager.

        Args:
            wallet: The wallet instance for signing transactions.
            service_key: Optional key (chain_name:service_id) to select a specific service.
                        If not provided, service operations require explicit service selection.

        """
        self.wallet = wallet
        self.global_config = Config()

        self.olas_config = self.global_config.plugins.get("olas")
        if isinstance(self.olas_config, dict):
            self.olas_config = OlasConfig(**self.olas_config)
            self.global_config.plugins["olas"] = self.olas_config
        elif self.olas_config is None:
            self.olas_config = OlasConfig()
            self.global_config.plugins["olas"] = self.olas_config

        # Get service by key if provided
        self.service = None
        if service_key and ":" in service_key:
            chain_name, service_id = service_key.split(":", 1)
            self.service = self.olas_config.get_service(chain_name, int(service_id))

        # Initialize contracts (default to gnosis)
        service_chain = getattr(self.service, "chain_name", "gnosis")
        chain_name = service_chain if isinstance(service_chain, str) else "gnosis"
        self._init_contracts(chain_name)

        # Initialize TransferService from wallet
        self.transfer_service = self.wallet.transfer_service

    def _init_contracts(self, chain_name: str) -> None:
        """Initialize contracts for the given chain."""
        chain_interface = ChainInterfaces().get(chain_name)

        # Get protocol contracts from plugin-local constants
        protocol_contracts = OLAS_CONTRACTS.get(chain_name.lower(), {})
        registry_address = protocol_contracts.get("OLAS_SERVICE_REGISTRY")
        manager_address = protocol_contracts.get("OLAS_SERVICE_MANAGER")

        if not registry_address or not manager_address:
            raise ValueError(f"OLAS contracts not found for chain: {chain_name}")

        self.registry = ServiceRegistryContract(registry_address, chain_name=chain_name)
        self.manager = ServiceManagerContract(manager_address, chain_name=chain_name)
        logger.info(f"[SM-INIT] ServiceManager initialized. Chain: {chain_name}")
        logger.info(f"[SM-INIT] Registry Address: {self.registry.address}")
        logger.info(f"[SM-INIT] Manager Address: {self.manager.address}")
        self.chain_interface = chain_interface
        self.chain_name = chain_name.lower()

    def _save_config(self) -> None:
        """Persist configuration to config.yaml."""
        self.global_config.save_config()

    def _update_and_save_service_state(self) -> None:
        """Update the service object in olas_config and persist to config.yaml."""
        if self.service:
            # Update the service object in the configuration dictionary
            # This ensures that changes to self.service (which comes from the Router)
            # are reflected in the ServiceManager's internal configuration state
            # before saving to disk.
            self.olas_config.add_service(self.service)
        self._save_config()

    def get(self) -> Optional[Dict]:
        """Get service details by ID."""
        if not self.service:
            logger.error("No active service")
            return None
        return self.registry.get_service(self.service.service_id)

    def get_service_state(self, service_id: Optional[int] = None) -> str:
        """Get the state of a service as a string.

        Args:
            service_id: Optional service ID. If not provided, uses the active service.

        Returns:
            The state name (e.g., 'DEPLOYED') or 'UNKNOWN' if not found.

        """
        if service_id is None:
            if not self.service:
                return "UNKNOWN"
            service_id = self.service.service_id

        try:
            info = self.registry.get_service(service_id)
            return info["state"].name
        except Exception as e:
            logger.debug(f"Failed to get service state for {service_id}: {e}")
            return "UNKNOWN"
