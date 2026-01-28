"""Olas service importer module.

Discover and import Olas services and their keys from external directories.
Supports two formats:
- .trader_runner (trader_alpha style)
- .operate (trader_xi style)
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from eth_account import Account
from loguru import logger

from iwa.core.keys import EncryptedAccount, KeyStorage
from iwa.core.models import Config, StoredSafeAccount

# Known mappings from olas-operate-middleware staking programs
# See: https://github.com/valory-xyz/olas-operate-middleware/blob/main/operate/ledger/profiles.py
STAKING_PROGRAM_MAP = {
    # Pearl staking programs (gnosis) - operate format
    "pearl_alpha": "0x5344B7DD311e5d3DdDd46A4f71481Bd7b05AAA3e",  # Expert Legacy
    "pearl_beta": "0x389B46C259631Acd6a69Bde8B6cEe218230bAE8C",  # Hobbyist 1 Legacy
    "pearl_beta_2": "0xE56dF1E563De1B10715cB313D514af350D207212",  # Expert 5 Legacy
    "pearl_beta_3": "0xD7A3C8b975f71030135f1a66E9e23164d54fF455",  # Expert 7 Legacy
    "pearl_beta_4": "0x17dBAe44BC5618Cc254055B386A29576b4F87015",  # Expert 9 Legacy
    "pearl_beta_5": "0xB0ef657b8302bd2c74B6E6D9B2b4b39145b19c6f",  # Expert 10 Legacy
    "pearl_beta_mm_v2_1": "0x75eeca6207be98cac3fde8a20ecd7b01e50b3472",  # Expert 3 MM v2
    "pearl_beta_mm_v2_2": "0x9c7f6103e3a72e4d1805b9c683ea5b370ec1a99f",  # Expert 4 MM v2
    "pearl_beta_mm_v2_3": "0xcdC603e0Ee55Aae92519f9770f214b2Be4967f7d",  # Expert 5 MM v2
    # Quickstart staking programs (gnosis) - quickstart format
    "quickstart_beta_expert_4": "0xaD9d891134443B443D7F30013c7e14Fe27F2E029",  # Expert 4 Legacy
    "quickstart_beta_expert_7": "0xD7A3C8b975f71030135f1a66E9e23164d54fF455",  # Expert 7 Legacy
    "quickstart_beta_expert_9": "0x17dBAe44BC5618Cc254055B386A29576b4F87015",  # Expert 9 Legacy
    "quickstart_beta_expert_11": "0x3112c1613eAC3dBAE3D4E38CeF023eb9E2C91CF7",  # Expert 11 Legacy
    "quickstart_beta_expert_16_mech_marketplace": "0x6c65430515c70a3f5E62107CC301685B7D46f991",  # Expert 16 MM v1
    "quickstart_beta_expert_18_mech_marketplace": "0x041e679d04Fc0D4f75Eb937Dea729Df09a58e454",  # Expert 18 MM v1
}


@dataclass
class DiscoveredKey:
    """A discovered Ethereum key."""

    address: str
    private_key: Optional[str] = None  # Plaintext hex (None if still encrypted)
    encrypted_keystore: Optional[dict] = None  # Web3 v3 keystore format
    source_file: Path = field(default_factory=Path)
    role: str = "unknown"  # "agent", "owner"
    is_encrypted: bool = False
    signature_verified: bool = False
    signature_failed: bool = False

    @property
    def is_decrypted(self) -> bool:
        """Check if we have the plaintext private key."""
        return self.private_key is not None


@dataclass
class DiscoveredSafe:
    """A discovered Safe multisig."""

    address: str
    chain_name: str = "gnosis"
    signers: List[str] = field(default_factory=list)


@dataclass
class DiscoveredService:
    """A discovered Olas service."""

    service_id: Optional[int] = None
    chain_name: str = "gnosis"
    safe_address: Optional[str] = None
    keys: List[DiscoveredKey] = field(default_factory=list)
    source_folder: Path = field(default_factory=Path)
    format: str = "unknown"  # "trader_runner" or "operate"
    service_name: Optional[str] = None
    # New fields for full service import
    staking_contract_address: Optional[str] = None
    service_owner_eoa_address: Optional[str] = None
    service_owner_multisig_address: Optional[str] = None

    @property
    def service_owner_address(self) -> Optional[str]:
        """Backward compatibility: effective owner address."""
        return self.service_owner_multisig_address or self.service_owner_eoa_address

    @property
    def agent_key(self) -> Optional[DiscoveredKey]:
        """Get the agent key if present."""
        for key in self.keys:
            if key.role == "agent":
                return key
        return None

    @property
    def operator_key(self) -> Optional[DiscoveredKey]:
        """Get the operator (owner) key. Alias for compatibility."""
        return self.owner_key

    @property
    def owner_key(self) -> Optional[DiscoveredKey]:
        """Get the owner key if present (matches 'owner' or 'operator' roles)."""
        for key in self.keys:
            if key.role in ["owner", "operator"]:
                return key
        return None


@dataclass
class ImportResult:
    """Result of an import operation."""

    success: bool
    message: str
    imported_keys: List[str] = field(default_factory=list)
    imported_safes: List[str] = field(default_factory=list)
    imported_services: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class OlasServiceImporter:
    """Discover and import Olas services from external directories."""

    def __init__(self, key_storage: Optional[KeyStorage] = None, password: Optional[str] = None):
        """Initialize the importer.

        Args:
            key_storage: KeyStorage instance. If None, will create one.
            password: Optional password to decrypt discovered keystores.

        """
        self.key_storage = key_storage or KeyStorage()
        self.config = Config()
        self.password = password

    def scan_directory(self, path: Path) -> List[DiscoveredService]:
        """Recursively scan a directory for Olas services.

        Args:
            path: Directory to scan.

        Returns:
            List of discovered services (deduplicated by chain:service_id).

        """
        path = Path(path)
        if not path.exists():
            logger.error(f"Path does not exist: {path}")
            return []

        discovered = []

        # Look for .trader_runner folders
        for trader_runner in path.rglob(".trader_runner"):
            if trader_runner.is_dir():
                service = self._parse_trader_runner_format(trader_runner)
                if service:
                    discovered.append(service)

        # Look for .operate folders
        for operate in path.rglob(".operate"):
            if operate.is_dir():
                services = self._parse_operate_format(operate)
                discovered.extend(services)

        return self._deduplicate_services(discovered)

    def _deduplicate_services(self, services: List[DiscoveredService]) -> List[DiscoveredService]:
        """Deduplicate discovered services by chain:service_id."""
        seen_keys: set = set()
        unique_services = []
        duplicates = 0
        for service in services:
            if service.service_id:
                key = f"{service.chain_name}:{service.service_id}"
                if key in seen_keys:
                    logger.debug(f"Skipping duplicate service {key} from {service.source_folder}")
                    duplicates += 1
                    continue
                seen_keys.add(key)
            unique_services.append(service)

        if duplicates:
            logger.info(f"Skipped {duplicates} duplicate service(s)")
        logger.info(f"Discovered {len(unique_services)} unique Olas service(s)")
        return unique_services

    def _find_trader_name(self, folder: Path) -> str:
        """Find the trader name by traversing up the directory tree.

        Handles quickstart format where the .operate folder is nested inside
        a quickstart folder, e.g.: trader_altair/quickstart/.operate/

        Returns the first folder name starting with 'trader_' or the
        immediate folder name if none found.
        """
        current = folder
        fallback = folder.name

        # Traverse up looking for trader_* folder
        for _ in range(5):  # Max 5 levels up
            if current.name.startswith("trader_"):
                return current.name
            current = current.parent
            if current == current.parent:  # Reached root
                break

        return fallback

    def _parse_trader_runner_format(self, folder: Path) -> Optional[DiscoveredService]:
        """Parse a .trader_runner folder.

        Expected files:
        - agent_pkey.txt: Encrypted keystore (JSON in .txt)
        - operator_pkey.txt: Encrypted keystore (JSON in .txt)
        - service_id.txt: Service ID
        - service_safe_address.txt: Safe address
        """
        logger.debug(f"Parsing trader_runner format: {folder}")

        service = DiscoveredService(
            source_folder=folder,
            format="trader_runner",
            service_name=folder.parent.name,
        )

        service.service_id = self._extract_service_id(folder)
        service.safe_address = self._extract_safe_address(folder)
        service.keys = self._extract_trader_keys(folder)

        # Extract staking program from .env
        self._extract_staking_from_env(service, folder)

        # Infer owner address from keys if not already set
        self._infer_owner_address(service)

        if not service.keys and not service.service_id:
            logger.debug(f"No valid data found in {folder}")
            return None

        return service

    def _extract_service_id(self, folder: Path) -> Optional[int]:
        """Extract service ID from file."""
        service_id_file = folder / "service_id.txt"
        if service_id_file.exists():
            try:
                return int(service_id_file.read_text().strip())
            except ValueError:
                logger.warning(f"Invalid service_id in {service_id_file}")
        return None

    def _extract_safe_address(self, folder: Path) -> Optional[str]:
        """Extract Safe address from file."""
        safe_file = folder / "service_safe_address.txt"
        if safe_file.exists():
            return safe_file.read_text().strip()
        return None

    def _extract_trader_keys(self, folder: Path) -> List[DiscoveredKey]:
        """Extract all keys from trader runner folder."""
        keys = []

        # Parse agent_pkey.txt (encrypted keystore in .txt)
        agent_file = folder / "agent_pkey.txt"
        if agent_file.exists():
            key = self._parse_keystore_file(agent_file, role="agent")
            if key:
                keys.append(key)

        # Parse operator_pkey.txt (contains owner key)
        operator_file = folder / "operator_pkey.txt"
        if operator_file.exists():
            key = self._parse_keystore_file(operator_file, role="owner")
            if key:
                keys.append(key)

        # Also check keys.json (array of keystores)
        keys_file = folder / "keys.json"
        if keys_file.exists():
            additional_keys = self._parse_keys_json(keys_file)
            # Avoid duplicates by address
            existing_addrs = {k.address.lower() for k in keys}
            for key in additional_keys:
                if key.address.lower() not in existing_addrs:
                    keys.append(key)
        return keys

    def _extract_staking_from_env(self, service: DiscoveredService, folder: Path) -> None:
        """Extract STAKING_PROGRAM from .env file in trader_runner folder."""
        # Check parent folder for .env (usually alongside .trader_runner)
        env_file = folder.parent / ".env"
        if not env_file.exists():
            # Also check inside the folder itself
            env_file = folder / ".env"
        if not env_file.exists():
            return

        try:
            content = env_file.read_text()
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("STAKING_PROGRAM="):
                    program_id = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if program_id:
                        service.staking_contract_address = self._resolve_staking_contract(
                            program_id, service.chain_name
                        )
                        logger.debug(f"Found STAKING_PROGRAM={program_id} in {env_file}")
                    break
        except IOError as e:
            logger.warning(f"Failed to read {env_file}: {e}")

    def _parse_operate_format(self, folder: Path) -> List[DiscoveredService]:
        """Parse a .operate folder.

        Expected structure:
        - wallets/ethereum.json: Wallet metadata
        - wallets/ethereum.txt: Owner key (plaintext JSON)
        - keys/0x...: Encrypted keystores
        - services/<uuid>/config.json: Service config with keys and service ID
        """
        logger.debug(f"Parsing operate format: {folder}")

        discovered = []

        # 1. Try to find services
        services = self._discover_operate_services(folder)
        discovered.extend(services)

        # 2. If no services, try standalone wallet
        if not discovered:
            wallet_service = self._discover_standalone_wallet(folder)
            if wallet_service:
                discovered.append(wallet_service)

        return discovered

    def _discover_operate_services(self, folder: Path) -> List[DiscoveredService]:
        """Discover services within .operate/services folder."""
        services = []
        services_folder = folder / "services"
        if services_folder.exists():
            for service_folder in services_folder.iterdir():
                if service_folder.is_dir():
                    config_file = service_folder / "config.json"
                    if config_file.exists():
                        service = self._parse_operate_service_config(config_file)
                        if service:
                            services.append(service)
        return services

    def _discover_standalone_wallet(self, folder: Path) -> Optional[DiscoveredService]:
        """Discover standalone wallet keys in .operate/wallets."""
        wallets_folder = folder / "wallets"
        if not wallets_folder.exists():
            return None

        # Create a placeholder service for standalone keys
        service = DiscoveredService(
            source_folder=folder,
            format="operate",
            service_name=folder.parent.name,
        )

        # Parse ethereum.txt (plaintext key)
        eth_txt = wallets_folder / "ethereum.txt"
        if eth_txt.exists():
            key = self._parse_plaintext_key_file(eth_txt, role="owner")
            if key:
                service.keys.append(key)

        # Parse ethereum.json for Safe info
        eth_json = wallets_folder / "ethereum.json"
        if eth_json.exists():
            try:
                data = json.loads(eth_json.read_text())
                if "safes" in data and "gnosis" in data["safes"]:
                    service.safe_address = data["safes"]["gnosis"]
            except (json.JSONDecodeError, KeyError):
                pass

        if service.keys:
            return service
        return None

    def _parse_operate_service_config(self, config_file: Path) -> Optional[DiscoveredService]:
        """Parse an operate service config.json file."""
        try:
            data = json.loads(config_file.read_text())
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON in {config_file}")
            return None

        # Use the folder name containing .operate (e.g., "trader_xi")
        operate_folder = config_file.parent.parent.parent  # services/<uuid> -> .operate
        parent_folder = operate_folder.parent  # .operate -> trader_xi or quickstart

        # Handle quickstart format: traverse up to find trader_* folder
        service_name = self._find_trader_name(parent_folder)

        service = DiscoveredService(
            source_folder=config_file.parent,
            format="operate",
            service_name=service_name,
        )

        # 1. Extract keys from config
        config_keys = self._extract_keys_from_operate_config(data, config_file)
        service.keys.extend(config_keys)

        # 2. Extract chain info
        self._enrich_service_with_chain_info(service, data)

        # 3. Check for wallet/owner keys in parent .operate folder
        parent_keys = self._extract_parent_wallet_keys(operate_folder)
        self._merge_unique_keys(service, parent_keys)

        # 4. Check for encrypted keys in keys folder
        external_keys = self._extract_external_keys_folder(operate_folder)
        self._merge_unique_keys(service, external_keys)

        # 5. Extract owner address from wallets folder
        self._extract_owner_address(service, operate_folder)

        # 6. Infer owner address from keys if not already set
        self._infer_owner_address(service)

        return service

    def _extract_keys_from_operate_config(
        self, data: dict, config_file: Path
    ) -> List[DiscoveredKey]:
        """Extract keys defined inside config.json."""
        keys = []
        if "keys" in data:
            for key_data in data["keys"]:
                if "private_key" in key_data and "address" in key_data:
                    private_key = key_data["private_key"]
                    # Remove 0x prefix if present
                    if private_key.startswith("0x"):
                        private_key = private_key[2:]
                    key = DiscoveredKey(
                        address=key_data["address"],
                        private_key=private_key,
                        role="agent",
                        source_file=config_file,
                        is_encrypted=False,
                    )
                    self._verify_key_signature(key)
                    keys.append(key)
        return keys

    def _enrich_service_with_chain_info(self, service: DiscoveredService, data: dict) -> None:
        """Extract service ID, Safe address, and staking contract from chain configs."""
        chain_configs = data.get("chain_configs", {})
        for chain_name, chain_config in chain_configs.items():
            chain_data = chain_config.get("chain_data", {})

            # "token" is actually the service_id in operate format
            if "token" in chain_data and isinstance(chain_data["token"], int):
                service.service_id = chain_data["token"]
                service.chain_name = chain_name

            if "multisig" in chain_data:
                service.safe_address = chain_data["multisig"]

            # Extract staking contract from user_params
            user_params = chain_data.get("user_params", {})
            staking_program_id = user_params.get("staking_program_id")
            if staking_program_id:
                service.staking_contract_address = self._resolve_staking_contract(
                    staking_program_id, chain_name
                )

    def _resolve_staking_contract(self, staking_program_id: str, chain_name: str) -> Optional[str]:
        """Resolve a staking program ID to a contract address."""
        address = STAKING_PROGRAM_MAP.get(staking_program_id)
        if address:
            logger.debug(f"Resolved staking program '{staking_program_id}' -> {address}")
        else:
            logger.warning(f"Unknown staking program ID: {staking_program_id}")
        return address

    def _extract_parent_wallet_keys(self, operate_folder: Path) -> List[DiscoveredKey]:
        """Extract owner keys from parent wallets folder."""
        keys = []
        wallets_folder = operate_folder / "wallets"
        if wallets_folder.exists():
            eth_txt = wallets_folder / "ethereum.txt"
            if eth_txt.exists():
                # Try plaintext first
                key = self._parse_plaintext_key_file(eth_txt, role="owner")
                if not key:
                    # Fallback to keystore
                    key = self._parse_keystore_file(eth_txt, role="owner")

                if key:
                    keys.append(key)
        return keys

    def _extract_external_keys_folder(self, operate_folder: Path) -> List[DiscoveredKey]:
        """Extract encrypted keys from the external keys folder."""
        keys = []
        keys_folder = operate_folder / "keys"
        if keys_folder.exists():
            for key_file in keys_folder.iterdir():
                if key_file.is_file() and key_file.name.startswith("0x"):
                    key = self._parse_keystore_file(key_file, role="agent")
                    if key:
                        keys.append(key)
        return keys

    def _extract_owner_address(self, service: DiscoveredService, operate_folder: Path) -> None:
        """Extract owner address from wallets/ethereum.json.

        Handles two cases:
        1. EOA is the owner (legacy).
        2. Safe is the owner, and EOA is a signer (new staking programs).
        """
        wallets_folder = operate_folder / "wallets"
        if not wallets_folder.exists():
            return

        eth_json = wallets_folder / "ethereum.json"
        if eth_json.exists():
            try:
                data = json.loads(eth_json.read_text())

                # Check for "safes" entry which indicates the owner is a Safe
                # Structure: "safes": { "gnosis": "0x..." }
                if (
                    "safes" in data and FLAGS_OWNER_SAFE in data["safes"]
                ):  # Need to detect chain dynamically or iterate
                    pass

                # Logic update:
                # 1. Capture EOA address always (it's the signer)
                eoa_address = data.get("address")

                # 2. Check for Safe Owner for the current service chain
                safe_owner_address = None
                if "safes" in data and isinstance(data["safes"], dict):
                    # We try to match with service.chain_name if available, usually "gnosis"
                    chain = service.chain_name or "gnosis"
                    safe_owner_address = data["safes"].get(chain)

                if safe_owner_address:
                    # CASE: Owner is Safe
                    service.service_owner_multisig_address = safe_owner_address
                    service.service_owner_eoa_address = (
                        eoa_address  # The EOA is the signer/controller
                    )

                    logger.debug(
                        f"Extracted Safe owner address: {safe_owner_address} (Signer: {eoa_address})"
                    )
                elif eoa_address:
                    # CASE: Owner is EOA
                    service.service_owner_eoa_address = eoa_address
                    service.service_owner_multisig_address = None
                    logger.debug(f"Extracted EOA owner address: {eoa_address}")

            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to parse {eth_json}: {e}")

    def _merge_unique_keys(self, service: DiscoveredService, new_keys: List[DiscoveredKey]):
        """Merge new keys into service avoiding duplicates by address."""
        existing_addrs = {k.address.lower() for k in service.keys}
        for key in new_keys:
            if key.address.lower() not in existing_addrs:
                service.keys.append(key)
                existing_addrs.add(key.address.lower())

    def _infer_owner_address(self, service: DiscoveredService) -> None:
        """Infer service_owner_eoa_address from keys with role='owner' if not already set."""
        if service.service_owner_eoa_address:
            return  # Already set

        for key in service.keys:
            if key.role == "owner" and key.address:
                service.service_owner_eoa_address = key.address
                logger.debug(f"Inferred owner EOA address from key: {key.address}")
                return

    def _parse_keystore_file(
        self, file_path: Path, role: str = "unknown"
    ) -> Optional[DiscoveredKey]:
        """Parse a web3 v3 keystore file."""
        try:
            content = file_path.read_text().strip()
            keystore = json.loads(content)

            # Validate it's a keystore
            if "crypto" not in keystore or "address" not in keystore:
                return None

            address = keystore.get("address", "")
            if not address.startswith("0x"):
                address = "0x" + address

            key = DiscoveredKey(
                address=address,
                encrypted_keystore=keystore,
                role=role,
                source_file=file_path,
                is_encrypted=True,
            )

            # Attempt decryption if password provided
            if self.password:
                self._attempt_decryption(key)
                if key.private_key:
                    self._verify_key_signature(key)

            return key
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to parse keystore {file_path}: {e}")
            return None

    def _parse_keys_json(self, file_path: Path) -> List[DiscoveredKey]:
        """Parse a keys.json file (array of keystores)."""
        try:
            content = json.loads(file_path.read_text())
            if not isinstance(content, list):
                return []

            keys = []
            for keystore in content:
                if "crypto" in keystore and "address" in keystore:
                    address = keystore.get("address", "")
                    if not address.startswith("0x"):
                        address = "0x" + address
                    key = DiscoveredKey(
                        address=address,
                        encrypted_keystore=keystore,
                        role="agent",
                        source_file=file_path,
                        is_encrypted=True,
                    )
                    # Attempt decryption if password provided
                    if self.password:
                        self._attempt_decryption(key)
                        if key.private_key:
                            self._verify_key_signature(key)
                    keys.append(key)
            return keys
        except (json.JSONDecodeError, IOError):
            return []

    def _parse_plaintext_key_file(
        self, file_path: Path, role: str = "unknown"
    ) -> Optional[DiscoveredKey]:
        """Parse a file containing a plaintext private key."""
        try:
            content = file_path.read_text().strip()

            # Try JSON format first ({"ledger": "ethereum", "address": "...", "private_key": "..."})
            try:
                data = json.loads(content)
                if isinstance(data, dict) and "private_key" in data and "address" in data:
                    key = DiscoveredKey(
                        address=data["address"],
                        private_key=data["private_key"],
                        role=role,
                        source_file=file_path,
                        is_encrypted=False,
                    )
                    self._verify_key_signature(key)
                    return key
            except json.JSONDecodeError:
                pass

            # Try raw hex format
            if len(content) == 64 or (len(content) == 66 and content.startswith("0x")):
                private_key = content[2:] if content.startswith("0x") else content
                account = Account.from_key(bytes.fromhex(private_key))
                key = DiscoveredKey(
                    address=account.address,
                    private_key=private_key,
                    role=role,
                    source_file=file_path,
                    is_encrypted=False,
                )
                self._verify_key_signature(key)
                return key

            return None
        except Exception as e:
            logger.warning(f"Failed to parse plaintext key {file_path}: {e}")
            return None

    def decrypt_key(self, key: DiscoveredKey, password: str) -> bool:
        """Decrypt an encrypted key.

        Args:
            key: The key to decrypt (modifies in place).
            password: Password for decryption.

        Returns:
            True if decryption succeeded.

        """
        if key.is_decrypted:
            return True

        if not key.encrypted_keystore:
            logger.error(f"No encrypted keystore for {key.address}")
            return False

        try:
            private_key = Account.decrypt(key.encrypted_keystore, password)
            key.private_key = private_key.hex()
            key.is_encrypted = False
            return True
        except ValueError as e:
            logger.warning(f"Failed to decrypt {key.address}: {e}")
            return False

    def import_service(
        self,
        service: DiscoveredService,
        password: Optional[str] = None,
    ) -> ImportResult:
        """Import a discovered service into the wallet.

        Args:
            service: The service to import.
            password: Password for encrypted keys (if any).

        Returns:
            ImportResult with details of what was imported.

        """
        result = ImportResult(success=True, message="")

        self._import_discovered_keys(service, password, result)
        self._import_discovered_safes(service, result)
        self._import_discovered_service_config(service, result)
        self._build_import_summary(result)

        return result

    def _import_discovered_keys(
        self, service: DiscoveredService, password: Optional[str], result: ImportResult
    ) -> None:
        """Import keys from the service."""
        for key in service.keys:
            key_result = self._import_key(key, service.service_name, password)
            if key_result[0]:
                result.imported_keys.append(key.address)
            elif key_result[1] == "duplicate":
                result.skipped.append(f"Key {key.address} (already exists)")
            else:
                result.errors.append(f"Key {key.address}: {key_result[1]}")
                result.success = False

    def _import_discovered_safes(self, service: DiscoveredService, result: ImportResult) -> None:
        """Import Safe from the service if present."""
        # 1. Import Agent Multisig (the one the agent controls)
        if service.safe_address:
            safe_result = self._import_safe(
                address=service.safe_address,
                signers=self._get_agent_signers(service),
                tag_suffix="multisig",  # e.g. trader_zeta_safe
                service_name=service.service_name,
            )
            if safe_result[0]:
                result.imported_safes.append(service.safe_address)
            elif safe_result[1] == "duplicate":
                result.skipped.append(f"Safe {service.safe_address} (already exists)")
            else:
                result.errors.append(f"Safe {service.safe_address}: {safe_result[1]}")

        # 2. Import Owner Safe (if it exists and is different)
        if (
            service.service_owner_multisig_address
            and service.service_owner_multisig_address != service.safe_address
        ):
            # Signer for Owner Safe is the EOA owner key
            owner_signers = self._get_owner_signers(service)

            safe_result = self._import_safe(
                address=service.service_owner_multisig_address,
                signers=owner_signers,
                tag_suffix="owner_multisig",  # e.g. trader_zeta_owner_safe
                service_name=service.service_name,
            )
            if safe_result[0]:
                result.imported_safes.append(service.service_owner_multisig_address)
                logger.info(f"Imported Owner Safe {service.service_owner_multisig_address}")

    def _get_agent_signers(self, service: DiscoveredService) -> List[str]:
        """Get list of signers for the agent safe."""
        signers = []
        for key in service.keys:
            if key.role == "agent":
                addr = key.address
                if not addr.startswith("0x"):
                    addr = "0x" + addr
                signers.append(addr)
        return signers

    def _get_owner_signers(self, service: DiscoveredService) -> List[str]:
        """Get list of signers for the owner safe."""
        signers = []
        for key in service.keys:
            # We look for keys marked as owner/operator
            if key.role in ["owner", "operator"]:
                addr = key.address
                if not addr.startswith("0x"):
                    addr = "0x" + addr
                signers.append(addr)
        return signers

    def _import_discovered_service_config(
        self, service: DiscoveredService, result: ImportResult
    ) -> None:
        """Import service config to OlasConfig."""
        if service.service_id:
            svc_result = self._import_service_config(service)
            if svc_result[0]:
                result.imported_services.append(f"{service.chain_name}:{service.service_id}")
            elif svc_result[1] == "duplicate":
                result.skipped.append(
                    f"Service {service.chain_name}:{service.service_id} (already exists)"
                )
            else:
                result.errors.append(
                    f"Service {service.chain_name}:{service.service_id}: {svc_result[1]}"
                )

    def _build_import_summary(self, result: ImportResult) -> None:
        """Build the summary message for the import result."""
        parts = []
        if result.imported_keys:
            parts.append(f"{len(result.imported_keys)} key(s)")
        if result.imported_safes:
            parts.append(f"{len(result.imported_safes)} safe(s)")
        if result.imported_services:
            parts.append(f"{len(result.imported_services)} service(s)")

        if parts:
            result.message = f"Imported {', '.join(parts)}"
        else:
            result.message = "Nothing imported"

    def _import_key(
        self, key: DiscoveredKey, service_name: Optional[str], password: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Import a single key.

        Returns:
            Tuple of (success, error_message_or_status)

        """
        # Check for duplicate
        existing = self.key_storage.find_stored_account(key.address)
        if existing:
            return False, "duplicate"

        # Decrypt if needed
        if not key.is_decrypted:
            if not password:
                return False, "encrypted key requires password"
            if not self.decrypt_key(key, password):
                return False, "decryption failed"

        # Generate tag
        tag = self._generate_tag(key, service_name)

        # Re-encrypt with our password and save
        try:
            encrypted = EncryptedAccount.encrypt_private_key(
                key.private_key,
                self.key_storage._password,
                tag,
            )
            self.key_storage.register_account(encrypted)
            logger.info(f"Imported key {key.address} as '{tag}'")
            return True, "ok"
        except Exception as e:
            return False, str(e)

    def _generate_tag(self, key: DiscoveredKey, service_name: Optional[str]) -> str:
        """Generate a unique tag for an imported key.

        Tags follow the pattern: {service_name}_{role}[_eoa]

        Examples:
          - trader_alpha_agent
          - trader_alpha_owner_eoa (EOA keys for owner role)

        """
        # Use service name as prefix, or 'imported' as fallback
        prefix = service_name or "imported"

        # Normalize: lowercase, replace spaces/special chars with underscores
        prefix = re.sub(r"[^a-z0-9]+", "_", prefix.lower()).strip("_")
        role = re.sub(r"[^a-z0-9]+", "_", key.role.lower()).strip("_")

        # Add _eoa suffix for owner/operator keys to distinguish from owner_safe
        if role in ["owner", "operator"]:
            base_tag = f"{prefix}_{role}_eoa"
        else:
            base_tag = f"{prefix}_{role}"

        # Check if tag already exists
        existing_tags = {
            acc.tag for acc in self.key_storage.accounts.values() if hasattr(acc, "tag")
        }

        if base_tag not in existing_tags:
            return base_tag

        # Add numeric suffix if tag already exists
        i = 2
        while f"{base_tag}_{i}" in existing_tags:
            i += 1
        return f"{base_tag}_{i}"

    def _import_safe(
        self,
        address: str,
        signers: List[str] = None,
        tag_suffix: str = "multisig",
        service_name: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Import a generic Safe."""
        if not address:
            return False, "no safe address"

        # Check for duplicate
        existing = self.key_storage.find_stored_account(address)
        if existing:
            return False, "duplicate"

        # Generate tag
        prefix = service_name or "imported"
        prefix = re.sub(r"[^a-z0-9]+", "_", prefix.lower()).strip("_")
        base_tag = f"{prefix}_{tag_suffix}"

        existing_tags = {
            acc.tag for acc in self.key_storage.accounts.values() if hasattr(acc, "tag")
        }
        tag = base_tag
        i = 2
        while tag in existing_tags:
            tag = f"{base_tag}_{i}"
            i += 1

        safe_account = StoredSafeAccount(
            tag=tag,
            address=address,
            chains=["gnosis"],  # TODO: detecting chain dynamically would be better
            threshold=1,  # Default, accurate value requires on-chain query
            signers=signers or [],
        )

        self.key_storage.register_account(safe_account)
        logger.info(f"Imported Safe {address} as '{tag}'")
        return True, "ok"

    def _import_service_config(self, service: DiscoveredService) -> Tuple[bool, str]:
        """Import service config to OlasConfig."""
        try:
            from iwa.plugins.olas.constants import OLAS_TOKEN_ADDRESS_GNOSIS
            from iwa.plugins.olas.models import OlasConfig, Service

            # Get or create OlasConfig
            if "olas" not in self.config.plugins:
                self.config.plugins["olas"] = OlasConfig()

            olas_config: OlasConfig = self.config.plugins["olas"]

            # Check for duplicate
            key = f"{service.chain_name}:{service.service_id}"
            if key in olas_config.services:
                return False, "duplicate"

            # Create service model with all fields
            olas_service = Service(
                service_name=service.service_name or f"service_{service.service_id}",
                chain_name=service.chain_name,
                service_id=service.service_id,
                agent_ids=[25],  # Trader agents always use agent ID 25
                multisig_address=service.safe_address,
                service_owner_eoa_address=service.service_owner_eoa_address,
                service_owner_multisig_address=service.service_owner_multisig_address,
                staking_contract_address=service.staking_contract_address,
                token_address=str(OLAS_TOKEN_ADDRESS_GNOSIS),
            )

            # Set agent address if we have one
            agent_key = service.agent_key
            if agent_key:
                olas_service.agent_address = agent_key.address

            olas_config.add_service(olas_service)
            self.config.save_config()
            logger.info(f"Imported service {key}")
            return True, "ok"

        except ImportError:
            return False, "Olas plugin not available"
        except Exception as e:
            return False, str(e)

    def _attempt_decryption(self, key: DiscoveredKey) -> None:
        """Attempt to decrypt an encrypted keystore using the provided password."""
        if not self.password or not key.encrypted_keystore:
            return

        try:
            logger.debug(f"Attempting decryption for {key.address}")

            # Use Account.decrypt to handle standard web3 keystores
            private_key_bytes = Account.decrypt(key.encrypted_keystore, self.password)
            key.private_key = private_key_bytes.hex()
            key.is_encrypted = False
            # If we successfully decrypted, it's no longer "encrypted" for verification purposes
            logger.debug(f"Successfully decrypted key for {key.address}")
        except ValueError as e:
            # Password incorrect
            logger.warning(f"Decryption failed (ValueError) for {key.address}: {e}")
        except Exception as e:
            logger.warning(f"Error decrypting key {key.address}: {type(e).__name__} - {e}")

    def _verify_key_signature(self, key: DiscoveredKey) -> None:
        """Verify that the plaintext private key can sign a message and recover the address."""
        if not key.private_key or not key.address:
            return

        try:
            from eth_account.messages import encode_defunct

            message = "Hello, world!"
            encoded_message = encode_defunct(text=message)
            signed_message = Account.sign_message(encoded_message, private_key=key.private_key)
            recovered_address = Account.recover_message(
                encoded_message, signature=signed_message.signature
            )

            # Normalize address to lowercase with 0x prefix
            key_addr = key.address.lower()
            if not key_addr.startswith("0x"):
                key_addr = "0x" + key_addr
            recovered_addr = recovered_address.lower()

            if recovered_addr == key_addr:
                key.signature_verified = True
                logger.debug(f"Signature verified for key {key.address}")
            else:
                key.signature_failed = True
                logger.warning(
                    f"Signature verification FAILED for key {key.address}. "
                    f"Recovered: {recovered_address}"
                )
        except Exception as e:
            key.signature_failed = True
            logger.warning(f"Error verifying signature for key {key.address}: {e}")


FLAGS_OWNER_SAFE = "deprecated"
