"""Tests for core SafeService."""

from unittest.mock import MagicMock, patch

import pytest

from iwa.core.keys import EncryptedAccount, KeyStorage
from iwa.core.services.safe import SafeService


@pytest.fixture
def mock_key_storage():
    """Mock key storage."""
    mock = MagicMock(spec=KeyStorage)
    mock.accounts = {}

    # Mock find_stored_account to return appropriate account types
    def find_account(tag_or_addr):
        if tag_or_addr == "deployer":
            acc = MagicMock(spec=EncryptedAccount)
            # Valid checksum address - Deployer
            acc.address = "0xAB7C8803962c0f2F5BBBe3FA8BF0Dcd705084223"
            return acc
        if tag_or_addr == "owner1":
            acc = MagicMock(spec=EncryptedAccount)
            # Valid checksum address - Owner
            acc.address = "0x5A0b54D5dc17e0AadC383d2db43B0a0D3E029c4c"
            return acc
        return None

    mock.find_stored_account.side_effect = find_account

    # Mock private key retrieval
    mock._get_private_key.return_value = (
        "0x1234567890123456789012345678901234567890123456789012345678901234"
    )

    return mock


@pytest.fixture
def mock_account_service():
    """Mock account service."""
    mock = MagicMock()
    mock.get_tag_by_address.return_value = "deployer_tag"
    return mock


@pytest.fixture
def mock_dependencies():
    """Mock external dependencies (Safe, EthereumClient, etc)."""
    with (
        patch("iwa.core.services.safe.EthereumClient") as mock_client,
        patch("iwa.plugins.gnosis.safe.get_ethereum_client") as mock_get_client,
        patch("iwa.core.services.safe.Safe") as mock_safe,
        patch("iwa.core.services.safe.ProxyFactory") as mock_proxy_factory,
        patch("iwa.core.services.safe.log_transaction") as mock_log,
        patch("iwa.core.services.safe.get_safe_master_copy_address") as mock_master,
        patch("iwa.core.services.safe.get_safe_proxy_factory_address") as mock_factory,
        patch("time.sleep"),  # Avoid any retry delays
    ):
        # Link get_ethereum_client to return the same mock as EthereumClient
        mock_get_client.return_value = mock_client.return_value
        # Setup Safe creation return
        mock_create_tx = MagicMock()
        # Valid Checksum Address - New Safe (Matches Pydantic output)
        mock_create_tx.contract_address = "0xbEC49fa140ACaa83533f900357DCD37866d50618"
        mock_create_tx.tx_hash.hex.return_value = "TxHash"

        mock_safe.create.return_value = mock_create_tx

        # Setup ProxyFactory return
        mock_deploy_tx = MagicMock()
        # Valid checksum address - Salted Safe
        mock_deploy_tx.contract_address = "0xDAFEA492D9c6733ae3d56b7Ed1ADB60692c98Bc5"
        mock_deploy_tx.tx_hash.hex.return_value = "TxHashSalted"

        mock_proxy_factory.return_value.deploy_proxy_contract_with_nonce.return_value = (
            mock_deploy_tx
        )

        # Fix for setup_data chaining
        mock_function = MagicMock()
        mock_function.build_transaction.return_value = {"data": "0x1234"}

        mock_contract = MagicMock()
        mock_contract.functions.setup.return_value = mock_function

        mock_safe_instance = MagicMock()
        mock_safe_instance.contract = mock_contract

        def safe_side_effect(*args, **kwargs):
            return mock_safe_instance

        mock_safe.side_effect = safe_side_effect
        mock_safe.create.return_value = mock_create_tx

        # Mock get_transaction_receipt for gas calc
        mock_client.return_value.w3.eth.get_transaction_receipt.return_value = {
            "gasUsed": 50000,
            "effectiveGasPrice": 20,
        }

        yield {
            "client": mock_client,
            "safe": mock_safe,
            "proxy_factory": mock_proxy_factory,
            "log": mock_log,
            "master": mock_master,
            "factory": mock_factory,
        }


def test_create_safe_standard(mock_key_storage, mock_account_service, mock_dependencies):
    """Test standard create_safe without salt."""
    service = SafeService(mock_key_storage, mock_account_service)

    safe_account, tx_hash = service.create_safe(
        deployer_tag_or_address="deployer",
        owner_tags_or_addresses=["owner1"],
        threshold=1,
        chain_name="gnosis",
        tag="MySafe",
    )

    # Checksum address matching what Pydantic/Web3 produces
    assert safe_account.address == "0xbEC49fa140ACaa83533f900357DCD37866d50618"
    assert safe_account.tag == "MySafe"
    assert tx_hash == "0xTxHash"

    mock_dependencies["safe"].create.assert_called_once()
    mock_key_storage.register_account.assert_called_once()


def test_create_safe_with_salt(mock_key_storage, mock_account_service, mock_dependencies):
    """Test create_safe with salt nonce."""
    service = SafeService(mock_key_storage, mock_account_service)

    mock_dependencies["client"].return_value.w3.eth.gas_price = 1000

    safe_account, tx_hash = service.create_safe(
        deployer_tag_or_address="deployer",
        owner_tags_or_addresses=["owner1"],
        threshold=1,
        chain_name="gnosis",
        tag="MySaltedSafe",
        salt_nonce=123,
    )

    # 0xDAFEA492D9c6733ae3d56b7Ed1ADB60692c98Bc5
    assert safe_account.address == "0xDAFEA492D9c6733ae3d56b7Ed1ADB60692c98Bc5"
    assert tx_hash == "0xTxHashSalted"

    # Check that manual ProxyFactory logic was used
    mock_dependencies[
        "proxy_factory"
    ].return_value.deploy_proxy_contract_with_nonce.assert_called_once()
    # Safe.create should NOT be called
    mock_dependencies["safe"].create.assert_not_called()


def test_create_safe_invalid_deployer(mock_key_storage, mock_account_service):
    """Test error when deployer invalid."""
    mock_key_storage.find_stored_account.return_value = None
    service = SafeService(mock_key_storage, mock_account_service)

    with pytest.raises(ValueError, match="Deployer account .* not found"):
        service.create_safe("invalid", [], 1, "gnosis")


# ---------------------------------------------------------------------------
# NonceAllocator tests
# ---------------------------------------------------------------------------

SAFE_ADDR = "0xbEC49fa140ACaa83533f900357DCD37866d50618"
CHAIN = "gnosis"


def _make_safe_service_with_nonce(nonce: int):
    """Return a SafeService whose get_safe_nonce returns nonce."""
    mock_ks = MagicMock()
    from iwa.core.models import StoredSafeAccount
    safe_acc = MagicMock(spec=StoredSafeAccount)
    safe_acc.address = SAFE_ADDR
    mock_ks.find_stored_account.return_value = safe_acc

    svc = SafeService(mock_ks, MagicMock())
    svc.get_safe_nonce = MagicMock(return_value=nonce)
    return svc


def test_nonce_allocator_sequential():
    """allocate() returns monotonically increasing nonces."""
    from iwa.core.services.safe import NonceAllocator
    svc = _make_safe_service_with_nonce(10)
    alloc = NonceAllocator(svc, SAFE_ADDR, CHAIN)
    assert alloc.allocate() == 10
    assert alloc.allocate() == 11
    assert alloc.allocate() == 12
    # Refetch called only once (on first allocate after invalidate)
    assert svc.get_safe_nonce.call_count == 1


def test_nonce_allocator_invalidate_triggers_refetch():
    """After invalidate(), next allocate() refetches the on-chain nonce."""
    from iwa.core.services.safe import NonceAllocator
    svc = _make_safe_service_with_nonce(5)
    alloc = NonceAllocator(svc, SAFE_ADDR, CHAIN)
    alloc.allocate()  # fetches → 5
    svc.get_safe_nonce.return_value = 7  # chain advanced externally
    alloc.invalidate("test")
    assert alloc.allocate() == 7
    assert svc.get_safe_nonce.call_count == 2


def test_nonce_allocator_concurrent():
    """5 concurrent allocate() calls from threads return unique nonces."""
    import threading

    from iwa.core.services.safe import NonceAllocator
    svc = _make_safe_service_with_nonce(0)
    alloc = NonceAllocator(svc, SAFE_ADDR, CHAIN)
    results = []
    threads = [threading.Thread(target=lambda: results.append(alloc.allocate())) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == list(range(5))


def test_nonce_allocator_refetch_failure_propagates():
    """If refetch raises, allocate() propagates the exception."""
    from iwa.core.services.safe import NonceAllocator
    svc = MagicMock()
    svc.get_safe_nonce.side_effect = ConnectionError("RPC down")
    alloc = NonceAllocator(svc, SAFE_ADDR, CHAIN)
    with pytest.raises(ConnectionError):
        alloc.allocate()
    assert alloc._refetch_failed_count == 1


def test_nonce_allocator_release_removes_from_in_flight():
    """release(nonce) removes nonce from _in_flight_nonces."""
    from iwa.core.services.safe import NonceAllocator
    svc = _make_safe_service_with_nonce(5)
    alloc = NonceAllocator(svc, SAFE_ADDR, CHAIN)
    n = alloc.allocate()
    assert n in alloc._in_flight_nonces
    alloc.release(n)
    assert n not in alloc._in_flight_nonces


def test_nonce_allocator_register_broadcast_stores_tx_hash():
    """register_broadcast stores tx_hash for in-flight nonce."""
    from iwa.core.services.safe import NonceAllocator
    svc = _make_safe_service_with_nonce(0)
    alloc = NonceAllocator(svc, SAFE_ADDR, CHAIN)
    n = alloc.allocate()
    alloc.register_broadcast(n, "0xdeadbeef")
    assert alloc._in_flight_txs[n] == "0xdeadbeef"
    alloc.release(n)
    assert n not in alloc._in_flight_txs


def test_invalidate_and_wait_drains_before_invalidating():
    """invalidate_and_wait() waits until all in-flight nonces are released."""
    import threading

    from iwa.core.services.safe import NonceAllocator

    svc = _make_safe_service_with_nonce(0)
    alloc = NonceAllocator(svc, SAFE_ADDR, CHAIN)

    n = alloc.allocate()
    assert not alloc._invalidated  # still valid after allocate

    invalidated_at = [None]
    released_at = [None]

    def _waiter():
        alloc.invalidate_and_wait(timeout=5.0, reason="test")
        import time
        invalidated_at[0] = time.monotonic()

    t = threading.Thread(target=_waiter)
    t.start()

    import time
    time.sleep(0.05)  # give the waiter thread time to start polling
    released_at[0] = time.monotonic()
    alloc.release(n)
    t.join(timeout=2.0)

    assert not t.is_alive(), "invalidate_and_wait should have returned"
    assert alloc._invalidated, "allocator must be marked invalid after wait"
    # invalidation happens AFTER release
    assert invalidated_at[0] >= released_at[0]


def test_invalidate_and_wait_timeout_forces_invalidation():
    """invalidate_and_wait() forces invalidation when timeout expires."""
    from iwa.core.services.safe import NonceAllocator

    svc = _make_safe_service_with_nonce(0)
    alloc = NonceAllocator(svc, SAFE_ADDR, CHAIN)
    alloc.allocate()  # nonce 0 in-flight, never released

    alloc.invalidate_and_wait(timeout=0.15, reason="test_timeout")
    assert alloc._invalidated, "must be invalidated even after timeout"


def test_eoa_gap_blocks_allocator():
    """allocate() raises NonceAllocatorBlockedError when EOA gap exceeds threshold."""
    from iwa.core.services.safe import NonceAllocator, NonceAllocatorBlockedError

    svc = MagicMock()
    svc.get_safe_nonce.return_value = 10
    svc.get_eoa_nonce_pair.return_value = (5, 9)  # gap=4 > threshold=3

    alloc = NonceAllocator(svc, SAFE_ADDR, CHAIN, gap_alert_threshold=3)
    with pytest.raises(NonceAllocatorBlockedError, match="EOA gap 4 > threshold 3"):
        alloc.allocate()
    assert alloc._blocked_until_gap_resolved


def test_eoa_gap_resolves_unblocks_allocator():
    """After gap resolves, next allocate() succeeds."""
    from iwa.core.services.safe import NonceAllocator, NonceAllocatorBlockedError

    svc = MagicMock()
    svc.get_safe_nonce.return_value = 10

    # First call: gap too large
    svc.get_eoa_nonce_pair.return_value = (5, 9)  # gap=4
    alloc = NonceAllocator(svc, SAFE_ADDR, CHAIN, gap_alert_threshold=3)
    with pytest.raises(NonceAllocatorBlockedError):
        alloc.allocate()

    # Gap resolves
    svc.get_eoa_nonce_pair.return_value = (8, 9)  # gap=1 <= 3
    n = alloc.allocate()  # should NOT raise; refetches on-chain nonce
    assert n == 10
    assert not alloc._blocked_until_gap_resolved


def test_eoa_gap_check_rpc_failure_does_not_block():
    """If get_eoa_nonce_pair raises, allocation continues without blocking."""
    from iwa.core.services.safe import NonceAllocator

    svc = MagicMock()
    svc.get_safe_nonce.return_value = 7
    svc.get_eoa_nonce_pair.side_effect = ConnectionError("RPC down")

    alloc = NonceAllocator(svc, SAFE_ADDR, CHAIN, gap_alert_threshold=3)
    n = alloc.allocate()  # should NOT raise despite get_eoa_nonce_pair failure
    assert n == 7
    assert not alloc._blocked_until_gap_resolved


def test_release_idempotent():
    """release(nonce) called twice does not raise and leaves a clean state."""
    from iwa.core.services.safe import NonceAllocator
    svc = _make_safe_service_with_nonce(0)
    alloc = NonceAllocator(svc, SAFE_ADDR, CHAIN)
    n = alloc.allocate()
    alloc.release(n)
    alloc.release(n)  # second call must not raise
    assert n not in alloc._in_flight_nonces
    assert n not in alloc._in_flight_txs


def test_invalidate_and_wait_timeout_clears_in_flight():
    """After timeout, _in_flight_nonces is cleared so future waits can drain."""
    from iwa.core.services.safe import NonceAllocator
    svc = _make_safe_service_with_nonce(0)
    alloc = NonceAllocator(svc, SAFE_ADDR, CHAIN)
    alloc.allocate()  # nonce 0 in-flight, never released
    alloc.invalidate_and_wait(timeout=0.1, reason="test_timeout")
    assert alloc._invalidated
    assert not alloc._in_flight_nonces, "Orphan nonces must be cleared after timeout"
    assert not alloc._in_flight_txs


def test_invalidate_and_wait_zero_timeout():
    """timeout=0 forces immediate invalidation even with nonces in-flight."""
    from iwa.core.services.safe import NonceAllocator
    svc = _make_safe_service_with_nonce(0)
    alloc = NonceAllocator(svc, SAFE_ADDR, CHAIN)
    alloc.allocate()  # in-flight
    alloc.invalidate_and_wait(timeout=0, reason="zero")
    assert alloc._invalidated
    assert not alloc._in_flight_nonces


def test_register_broadcast_with_invalid_nonce_does_not_raise():
    """register_broadcast with a nonce not in-flight logs debug but doesn't crash."""
    from iwa.core.services.safe import NonceAllocator
    svc = _make_safe_service_with_nonce(0)
    alloc = NonceAllocator(svc, SAFE_ADDR, CHAIN)
    # nonce 99 was never allocated — should not raise
    alloc.register_broadcast(99, "0xdeadbeef")
    assert 99 not in alloc._in_flight_txs


def test_get_allocator_warns_if_threshold_differs(caplog):
    """get_allocator logs a warning when a second caller passes a different threshold."""
    import logging
    svc = _make_safe_service_with_nonce(0)
    svc.get_allocator(SAFE_ADDR, CHAIN, gap_alert_threshold=3)
    with caplog.at_level(logging.WARNING, logger="iwa"):
        svc.get_allocator(SAFE_ADDR, CHAIN, gap_alert_threshold=5)
    assert any("threshold mismatch" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# SafeService.get_allocator tests
# ---------------------------------------------------------------------------


def test_get_allocator_returns_same_instance():
    """get_allocator called twice for same (safe, chain) returns same object."""
    svc = _make_safe_service_with_nonce(0)
    a1 = svc.get_allocator(SAFE_ADDR, CHAIN)
    a2 = svc.get_allocator(SAFE_ADDR, CHAIN)
    assert a1 is a2


def test_get_allocator_different_chains_are_isolated():
    """Allocators for different chains are independent instances."""
    svc = _make_safe_service_with_nonce(0)
    a_gnosis = svc.get_allocator(SAFE_ADDR, "gnosis")
    a_base = svc.get_allocator(SAFE_ADDR, "base")
    assert a_gnosis is not a_base


def test_allocators_isolated_between_safe_service_instances():
    """Two SafeService instances have independent allocator registries (S1)."""
    svc1 = _make_safe_service_with_nonce(0)
    svc2 = _make_safe_service_with_nonce(0)
    a1 = svc1.get_allocator(SAFE_ADDR, CHAIN)
    a2 = svc2.get_allocator(SAFE_ADDR, CHAIN)
    assert a1 is not a2


# ---------------------------------------------------------------------------
# execute_safe_transaction: safe_nonce + allow_nonce_refresh propagation
# ---------------------------------------------------------------------------


def _make_safe_service_for_execute():
    """SafeService with all chain/Safe dependencies mocked out."""
    from iwa.core.models import StoredSafeAccount
    mock_ks = MagicMock()
    safe_acc = MagicMock(spec=StoredSafeAccount)
    safe_acc.address = SAFE_ADDR
    safe_acc.tag = "mech"
    safe_acc.signers = ["0x5A0b54D5dc17e0AadC383d2db43B0a0D3E029c4c"]
    safe_acc.threshold = 1
    mock_ks.find_stored_account.return_value = safe_acc
    mock_ks._get_private_key.return_value = "0x" + "ab" * 32
    svc = SafeService(mock_ks, MagicMock())
    return svc, safe_acc


def test_execute_safe_transaction_passes_safe_nonce():
    """safe_nonce is forwarded to build_tx."""
    svc, safe_acc = _make_safe_service_for_execute()
    with (
        patch("iwa.core.services.safe.SafeService._get_ethereum_client"),
        patch("iwa.plugins.gnosis.safe.SafeMultisig") as mock_sm,
        patch("iwa.core.services.safe.SafeService._sign_and_execute_safe_tx", return_value="0xtx"),
    ):
        mock_instance = MagicMock()
        mock_sm.return_value = mock_instance
        svc.execute_safe_transaction(SAFE_ADDR, "0x1234" + "0" * 36, 0, CHAIN, safe_nonce=42)
        mock_instance.build_tx.assert_called_once()
        _, kwargs = mock_instance.build_tx.call_args
        assert kwargs["safe_nonce"] == 42


def test_execute_safe_transaction_passes_allow_nonce_refresh_false():
    """allow_nonce_refresh=False is forwarded to _sign_and_execute_safe_tx."""
    svc, safe_acc = _make_safe_service_for_execute()
    with (
        patch("iwa.core.services.safe.SafeService._get_ethereum_client"),
        patch("iwa.plugins.gnosis.safe.SafeMultisig"),
        patch("iwa.core.services.safe.SafeService._sign_and_execute_safe_tx", return_value="0xtx") as mock_sign,
    ):
        svc.execute_safe_transaction(SAFE_ADDR, "0x1234" + "0" * 36, 0, CHAIN, allow_nonce_refresh=False)
        _, kwargs = mock_sign.call_args
        assert kwargs["allow_nonce_refresh"] is False


# ---------------------------------------------------------------------------
# Signer key isolation assertion (S4 / R1)
# ---------------------------------------------------------------------------


def test_signer_keys_sharing_raises():
    """Concurrent use of the same signer_keys list object raises RuntimeError."""
    import threading
    svc, _ = _make_safe_service_for_execute()
    same_list = ["0x" + "ab" * 32]
    errors = []

    def first():
        list_id = id(same_list)
        with svc._active_signer_lists_lock:
            svc._active_signer_lists.add(list_id)
        errors.append(None)

    def second():
        import time
        time.sleep(0.01)
        try:
            with patch("iwa.core.services.safe.SafeService._get_signer_keys", return_value=same_list):
                with patch("iwa.core.services.safe_executor.SafeTransactionExecutor.execute_with_retry",
                           return_value=(True, "0xtx", None)):
                    svc._sign_and_execute_safe_tx(MagicMock(), same_list, "gnosis", SAFE_ADDR)
        except RuntimeError as e:
            errors.append(e)

    t1 = threading.Thread(target=first)
    t2 = threading.Thread(target=second)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert any(isinstance(e, RuntimeError) for e in errors), "Expected RuntimeError for shared signer_keys"
