"""Tests for tools modules: wallet_check and list_contracts.

Covers iwa.tools.wallet_check and iwa.tools.list_contracts
by mocking external dependencies (KeyStorage, secrets, StakingContract, etc.).
"""

import datetime
from unittest.mock import MagicMock, patch

import pytest

# Valid Ethereum addresses for tests
ADDR_EOA1 = "0x1111111111111111111111111111111111111111"
ADDR_EOA2 = "0x2222222222222222222222222222222222222222"
ADDR_SAFE = "0x3333333333333333333333333333333333333333"


# ===========================================================================
# wallet_check tests
# ===========================================================================


class TestCheckAccounts:
    """Test _check_accounts function."""

    def test_no_accounts(self, capsys):
        """Test with empty wallet."""
        from iwa.tools.wallet_check import _check_accounts

        storage = MagicMock()
        storage.accounts = {}

        result = _check_accounts(storage)

        assert result is True
        captured = capsys.readouterr()
        assert "No accounts found" in captured.out

    def test_eoa_decrypt_success(self, capsys):
        """Test successful EOA decryption verification."""
        from iwa.tools.wallet_check import _check_accounts

        mock_account = MagicMock()
        mock_account.tag = "MyEOA"
        mock_account.address = ADDR_EOA1
        mock_account.decrypt_private_key.return_value = "0xprivatekey"
        # Not a StoredSafeAccount
        mock_account.__class__ = type("EncryptedAccount", (), {})

        storage = MagicMock()
        storage.accounts = {ADDR_EOA1: mock_account}

        with patch("iwa.tools.wallet_check.Account") as mock_eth_account:
            derived = MagicMock()
            derived.address = ADDR_EOA1
            mock_eth_account.from_key.return_value = derived

            result = _check_accounts(storage)

        assert result is True
        captured = capsys.readouterr()
        assert "OK" in captured.out
        assert "Accounts Verified: 1" in captured.out

    def test_eoa_address_mismatch(self, capsys):
        """Test EOA with address mismatch."""
        from iwa.tools.wallet_check import _check_accounts

        mock_account = MagicMock()
        mock_account.tag = "BadEOA"
        mock_account.address = ADDR_EOA1
        mock_account.decrypt_private_key.return_value = "0xprivatekey"
        mock_account.__class__ = type("EncryptedAccount", (), {})

        storage = MagicMock()
        storage.accounts = {ADDR_EOA1: mock_account}

        with patch("iwa.tools.wallet_check.Account") as mock_eth_account:
            derived = MagicMock()
            derived.address = ADDR_EOA2  # Different address
            mock_eth_account.from_key.return_value = derived

            result = _check_accounts(storage)

        assert result is False
        captured = capsys.readouterr()
        assert "ADDRESS MISMATCH" in captured.out
        assert "Accounts Failed:   1" in captured.out

    def test_eoa_decrypt_failure(self, capsys):
        """Test EOA decryption failure."""
        from iwa.tools.wallet_check import _check_accounts

        mock_account = MagicMock()
        mock_account.tag = "CorruptEOA"
        mock_account.address = ADDR_EOA1
        mock_account.decrypt_private_key.side_effect = Exception("Bad password")
        mock_account.__class__ = type("EncryptedAccount", (), {})

        storage = MagicMock()
        storage.accounts = {ADDR_EOA1: mock_account}

        result = _check_accounts(storage)

        assert result is False
        captured = capsys.readouterr()
        assert "DECRYPTION FAILED" in captured.out

    def test_safe_account_skipped(self, capsys):
        """Test that Safe accounts are skipped."""
        from iwa.core.models import StoredSafeAccount
        from iwa.tools.wallet_check import _check_accounts

        mock_safe = MagicMock(spec=StoredSafeAccount)
        mock_safe.tag = "MySafe"
        mock_safe.address = ADDR_SAFE

        storage = MagicMock()
        storage.accounts = {ADDR_SAFE: mock_safe}

        result = _check_accounts(storage)

        assert result is True
        captured = capsys.readouterr()
        assert "Safe" in captured.out
        assert "Skipped" in captured.out
        assert "Safes Skipped:     1" in captured.out

    def test_mixed_accounts(self, capsys):
        """Test with mix of EOA (ok), EOA (bad), and Safe."""
        from iwa.core.models import StoredSafeAccount
        from iwa.tools.wallet_check import _check_accounts

        # Good EOA
        good_eoa = MagicMock()
        good_eoa.tag = "GoodEOA"
        good_eoa.address = ADDR_EOA1
        good_eoa.decrypt_private_key.return_value = "0xgood"
        good_eoa.__class__ = type("EncryptedAccount", (), {})

        # Bad EOA
        bad_eoa = MagicMock()
        bad_eoa.tag = "BadEOA"
        bad_eoa.address = ADDR_EOA2
        bad_eoa.decrypt_private_key.side_effect = Exception("fail")
        bad_eoa.__class__ = type("EncryptedAccount", (), {})

        # Safe
        safe_acct = MagicMock(spec=StoredSafeAccount)
        safe_acct.tag = "MySafe"
        safe_acct.address = ADDR_SAFE

        storage = MagicMock()
        storage.accounts = {
            ADDR_EOA1: good_eoa,
            ADDR_EOA2: bad_eoa,
            ADDR_SAFE: safe_acct,
        }

        with patch("iwa.tools.wallet_check.Account") as mock_eth_account:
            derived = MagicMock()
            derived.address = ADDR_EOA1
            mock_eth_account.from_key.return_value = derived

            result = _check_accounts(storage)

        assert result is False
        captured = capsys.readouterr()
        assert "Accounts Verified: 1" in captured.out
        assert "Accounts Failed:   1" in captured.out
        assert "Safes Skipped:     1" in captured.out


class TestCheckMnemonic:
    """Test _check_mnemonic function."""

    def test_no_mnemonic(self, capsys):
        """Test when no mnemonic is stored."""
        from iwa.tools.wallet_check import _check_mnemonic

        storage = MagicMock()
        storage.encrypted_mnemonic = None

        result = _check_mnemonic(storage)

        assert result is True
        captured = capsys.readouterr()
        assert "No encrypted mnemonic" in captured.out

    def test_successful_12_word_mnemonic(self, capsys):
        """Test successful 12-word mnemonic decryption."""
        from iwa.tools.wallet_check import _check_mnemonic

        storage = MagicMock()
        storage.encrypted_mnemonic = {"kdf_salt": "abc", "nonce": "def", "ciphertext": "ghi"}

        mock_enc_mnemonic = MagicMock()
        mock_enc_mnemonic.decrypt.return_value = " ".join(["word"] * 12)

        with (
            patch("iwa.tools.wallet_check.EncryptedMnemonic", return_value=mock_enc_mnemonic),
            patch("iwa.tools.wallet_check.secrets") as mock_secrets,
        ):
            mock_secrets.wallet_password.get_secret_value.return_value = "testpass"
            result = _check_mnemonic(storage)

        assert result is True
        captured = capsys.readouterr()
        assert "Decryption successful (12 words)" in captured.out

    def test_successful_24_word_mnemonic(self, capsys):
        """Test successful 24-word mnemonic decryption."""
        from iwa.tools.wallet_check import _check_mnemonic

        storage = MagicMock()
        storage.encrypted_mnemonic = {"kdf_salt": "abc", "nonce": "def", "ciphertext": "ghi"}

        mock_enc_mnemonic = MagicMock()
        mock_enc_mnemonic.decrypt.return_value = " ".join(["word"] * 24)

        with (
            patch("iwa.tools.wallet_check.EncryptedMnemonic", return_value=mock_enc_mnemonic),
            patch("iwa.tools.wallet_check.secrets") as mock_secrets,
        ):
            mock_secrets.wallet_password.get_secret_value.return_value = "testpass"
            result = _check_mnemonic(storage)

        assert result is True
        captured = capsys.readouterr()
        assert "24 words" in captured.out

    def test_unusual_word_count(self, capsys):
        """Test mnemonic with unusual word count."""
        from iwa.tools.wallet_check import _check_mnemonic

        storage = MagicMock()
        storage.encrypted_mnemonic = {"kdf_salt": "abc", "nonce": "def", "ciphertext": "ghi"}

        mock_enc_mnemonic = MagicMock()
        mock_enc_mnemonic.decrypt.return_value = " ".join(["word"] * 7)  # unusual

        with (
            patch("iwa.tools.wallet_check.EncryptedMnemonic", return_value=mock_enc_mnemonic),
            patch("iwa.tools.wallet_check.secrets") as mock_secrets,
        ):
            mock_secrets.wallet_password.get_secret_value.return_value = "testpass"
            result = _check_mnemonic(storage)

        assert result is True
        captured = capsys.readouterr()
        assert "unusual word count" in captured.out

    def test_empty_decryption(self, capsys):
        """Test mnemonic decrypts to empty string."""
        from iwa.tools.wallet_check import _check_mnemonic

        storage = MagicMock()
        storage.encrypted_mnemonic = {"kdf_salt": "abc", "nonce": "def", "ciphertext": "ghi"}

        mock_enc_mnemonic = MagicMock()
        mock_enc_mnemonic.decrypt.return_value = ""

        with (
            patch("iwa.tools.wallet_check.EncryptedMnemonic", return_value=mock_enc_mnemonic),
            patch("iwa.tools.wallet_check.secrets") as mock_secrets,
        ):
            mock_secrets.wallet_password.get_secret_value.return_value = "testpass"
            result = _check_mnemonic(storage)

        assert result is False
        captured = capsys.readouterr()
        assert "empty string" in captured.out

    def test_decryption_exception(self, capsys):
        """Test mnemonic decryption failure."""
        from iwa.tools.wallet_check import _check_mnemonic

        storage = MagicMock()
        storage.encrypted_mnemonic = {"kdf_salt": "abc", "nonce": "def", "ciphertext": "ghi"}

        mock_enc_mnemonic = MagicMock()
        mock_enc_mnemonic.decrypt.side_effect = Exception("Invalid key")

        with (
            patch("iwa.tools.wallet_check.EncryptedMnemonic", return_value=mock_enc_mnemonic),
            patch("iwa.tools.wallet_check.secrets") as mock_secrets,
        ):
            mock_secrets.wallet_password.get_secret_value.return_value = "testpass"
            result = _check_mnemonic(storage)

        assert result is False
        captured = capsys.readouterr()
        assert "FAILED" in captured.out


class TestCheckWallet:
    """Test check_wallet entry point."""

    def test_all_pass(self, capsys):
        """Test check_wallet when all checks pass."""
        from iwa.tools.wallet_check import check_wallet

        mock_storage = MagicMock()
        mock_storage.accounts = {}
        mock_storage.encrypted_mnemonic = None

        with (
            patch("iwa.tools.wallet_check.KeyStorage", return_value=mock_storage),
            pytest.raises(SystemExit) as exc_info,
        ):
            check_wallet()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "All checks passed" in captured.out

    def test_keystorage_init_fails(self, capsys):
        """Test check_wallet when KeyStorage init fails."""
        from iwa.tools.wallet_check import check_wallet

        with (
            patch("iwa.tools.wallet_check.KeyStorage", side_effect=Exception("No wallet")),
            pytest.raises(SystemExit) as exc_info,
        ):
            check_wallet()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Critical Error" in captured.out

    def test_checks_fail(self, capsys):
        """Test check_wallet when some checks fail."""
        from iwa.tools.wallet_check import check_wallet

        mock_storage = MagicMock()
        # EOA that will fail
        mock_account = MagicMock()
        mock_account.tag = "BadEOA"
        mock_account.address = ADDR_EOA1
        mock_account.decrypt_private_key.side_effect = Exception("fail")
        mock_account.__class__ = type("EncryptedAccount", (), {})
        mock_storage.accounts = {ADDR_EOA1: mock_account}
        mock_storage.encrypted_mnemonic = None

        with (
            patch("iwa.tools.wallet_check.KeyStorage", return_value=mock_storage),
            pytest.raises(SystemExit) as exc_info,
        ):
            check_wallet()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "FAILED" in captured.out


# ===========================================================================
# list_contracts tests
# ===========================================================================


class TestParseArgs:
    """Test parse_args."""

    def test_default_args(self):
        """Test default argument parsing."""
        from iwa.tools.list_contracts import parse_args

        with patch("sys.argv", ["list_contracts"]):
            args = parse_args()
            assert args.sort == "name"

    def test_sort_by_rewards(self):
        """Test sorting by rewards."""
        from iwa.tools.list_contracts import parse_args

        with patch("sys.argv", ["list_contracts", "--sort", "rewards"]):
            args = parse_args()
            assert args.sort == "rewards"

    def test_sort_by_slots(self):
        """Test sorting by slots."""
        from iwa.tools.list_contracts import parse_args

        with patch("sys.argv", ["list_contracts", "--sort", "slots"]):
            args = parse_args()
            assert args.sort == "slots"


class TestFetchContractData:
    """Test fetch_contract_data."""

    def test_fetches_data_successfully(self):
        """Test successful contract data fetching."""
        from iwa.tools.list_contracts import fetch_contract_data

        mock_contract = MagicMock()
        mock_contract.min_staking_deposit = 100 * 10**18
        mock_contract.get_service_ids.return_value = [1, 2, 3]
        mock_contract.max_num_services = 10
        mock_contract.available_rewards = 500 * 10**18
        mock_contract.balance = 1000 * 10**18
        mock_contract.get_next_epoch_start.return_value = datetime.datetime(2026, 3, 1)

        with (
            patch(
                "iwa.tools.list_contracts.OLAS_TRADER_STAKING_CONTRACTS",
                {"gnosis": {"Contract1": "0xaddr1"}},
            ),
            patch("iwa.tools.list_contracts.StakingContract", return_value=mock_contract),
            patch("iwa.tools.list_contracts.track", side_effect=lambda items, **kw: items),
        ):
            data = fetch_contract_data("gnosis")

        assert len(data) == 1
        assert data[0]["name"] == "Contract1"
        assert data[0]["needed_olas"] == 200.0  # (100 * 2)
        assert data[0]["occupied_slots"] == 3
        assert data[0]["free_slots"] == 7
        assert data[0]["rewards_olas"] == 500.0
        assert data[0]["error"] is None

    def test_handles_contract_error(self):
        """Test handling contract initialization error."""
        from iwa.tools.list_contracts import fetch_contract_data

        with (
            patch(
                "iwa.tools.list_contracts.OLAS_TRADER_STAKING_CONTRACTS",
                {"gnosis": {"BadContract": "0xbad"}},
            ),
            patch("iwa.tools.list_contracts.StakingContract", side_effect=Exception("RPC fail")),
            patch("iwa.tools.list_contracts.track", side_effect=lambda items, **kw: items),
        ):
            data = fetch_contract_data("gnosis")

        assert len(data) == 1
        assert data[0]["name"] == "BadContract"
        assert data[0]["error"] == "RPC fail"

    def test_empty_chain(self):
        """Test with empty contract map."""
        from iwa.tools.list_contracts import fetch_contract_data

        with (
            patch("iwa.tools.list_contracts.OLAS_TRADER_STAKING_CONTRACTS", {"gnosis": {}}),
            patch("iwa.tools.list_contracts.track", side_effect=lambda items, **kw: items),
        ):
            data = fetch_contract_data("gnosis")

        assert data == []


class TestSortContractData:
    """Test sort_contract_data."""

    def _make_contract_data(self):
        """Create sample contract data for sorting tests."""
        return [
            {
                "name": "Beta",
                "needed_olas": 200,
                "free_slots": 5,
                "rewards_olas": 100,
                "epoch_end": datetime.datetime(2026, 3, 1),
                "error": None,
            },
            {
                "name": "Alpha",
                "needed_olas": 100,
                "free_slots": 10,
                "rewards_olas": 500,
                "epoch_end": datetime.datetime(2026, 2, 1),
                "error": None,
            },
            {
                "name": "Gamma",
                "error": "failed",
            },
        ]

    def test_sort_by_name(self):
        """Test sorting by name."""
        from iwa.tools.list_contracts import sort_contract_data

        data = self._make_contract_data()
        sort_contract_data(data, "name")
        assert data[0]["name"] == "Alpha"
        assert data[1]["name"] == "Beta"
        assert data[2]["name"] == "Gamma"

    def test_sort_by_rewards(self):
        """Test sorting by rewards (descending)."""
        from iwa.tools.list_contracts import sort_contract_data

        data = self._make_contract_data()
        sort_contract_data(data, "rewards")
        assert data[0]["rewards_olas"] == 500
        assert data[1]["rewards_olas"] == 100
        # Error item goes to end (sorted as -1)

    def test_sort_by_epoch(self):
        """Test sorting by epoch end."""
        from iwa.tools.list_contracts import sort_contract_data

        data = self._make_contract_data()
        sort_contract_data(data, "epoch")
        assert data[0]["name"] == "Alpha"  # earliest epoch
        assert data[1]["name"] == "Beta"

    def test_sort_by_slots(self):
        """Test sorting by free slots (descending)."""
        from iwa.tools.list_contracts import sort_contract_data

        data = self._make_contract_data()
        sort_contract_data(data, "slots")
        assert data[0]["free_slots"] == 10
        assert data[1]["free_slots"] == 5

    def test_sort_by_olas(self):
        """Test sorting by needed OLAS (ascending)."""
        from iwa.tools.list_contracts import sort_contract_data

        data = self._make_contract_data()
        sort_contract_data(data, "olas")
        assert data[0]["needed_olas"] == 100
        assert data[1]["needed_olas"] == 200


class TestPrintTable:
    """Test print_table."""

    def test_prints_successful_contracts(self):
        """Test printing table with successful data."""
        from iwa.tools.list_contracts import print_table

        console = MagicMock()
        data = [
            {
                "name": "Contract1",
                "needed_olas": 200.0,
                "occupied_slots": 3,
                "max_slots": 10,
                "free_slots": 7,
                "rewards_olas": 500.0,
                "balance_olas": 1000.0,
                "epoch_end": datetime.datetime(2026, 3, 1, 12, 0, 0),
                "error": None,
            }
        ]

        print_table(console, data, "gnosis", "name")
        console.print.assert_called_once()

    def test_prints_error_contracts(self):
        """Test printing table with error data."""
        from iwa.tools.list_contracts import print_table

        console = MagicMock()
        data = [{"name": "BadContract", "error": "RPC down"}]

        print_table(console, data, "gnosis", "name")
        console.print.assert_called_once()

    def test_prints_mixed_data(self):
        """Test printing table with mix of success and error."""
        from iwa.tools.list_contracts import print_table

        console = MagicMock()
        data = [
            {
                "name": "Good",
                "needed_olas": 100.0,
                "occupied_slots": 1,
                "max_slots": 5,
                "free_slots": 4,
                "rewards_olas": 50.0,
                "balance_olas": 200.0,
                "epoch_end": datetime.datetime(2026, 3, 1, 12, 0, 0),
                "error": None,
            },
            {"name": "Bad", "error": "timeout"},
        ]

        print_table(console, data, "gnosis", "rewards")
        console.print.assert_called_once()


class TestMain:
    """Test main entry point."""

    def test_main_no_contracts(self):
        """Test main when no contracts found for chain."""
        from iwa.tools.list_contracts import main

        with (
            patch("iwa.tools.list_contracts.parse_args") as mock_args,
            patch("iwa.tools.list_contracts.OLAS_TRADER_STAKING_CONTRACTS", {}),
            patch("iwa.tools.list_contracts.Console") as mock_console_cls,
        ):
            mock_args.return_value.sort = "name"
            main()
            mock_console_cls.return_value.print.assert_called_once()

    def test_main_success(self):
        """Test main with successful flow."""
        from iwa.tools.list_contracts import main

        with (
            patch("iwa.tools.list_contracts.parse_args") as mock_args,
            patch(
                "iwa.tools.list_contracts.OLAS_TRADER_STAKING_CONTRACTS",
                {"gnosis": {"C1": "0xaddr"}},
            ),
            patch("iwa.tools.list_contracts.fetch_contract_data", return_value=[]) as mock_fetch,
            patch("iwa.tools.list_contracts.sort_contract_data") as mock_sort,
            patch("iwa.tools.list_contracts.print_table") as mock_print,
            patch("iwa.tools.list_contracts.Console"),
        ):
            mock_args.return_value.sort = "name"
            main()
            mock_fetch.assert_called_once_with("gnosis")
            mock_sort.assert_called_once()
            mock_print.assert_called_once()


# ===========================================================================
# Modal on_button_pressed tests (covering base.py uncovered lines)
# ===========================================================================


class TestCreateEOAModalButtonPress:
    """Test CreateEOAModal.on_button_pressed (lines 68-72)."""

    def test_create_button(self):
        """Test pressing create button dismisses with tag."""
        from iwa.tui.modals.base import CreateEOAModal

        modal = CreateEOAModal.__new__(CreateEOAModal)
        mock_input = MagicMock()
        mock_input.value = "MyNewEOA"
        modal.query_one = MagicMock(return_value=mock_input)
        modal.dismiss = MagicMock()

        event = MagicMock()
        event.button.id = "create"
        modal.on_button_pressed(event)

        modal.dismiss.assert_called_once_with("MyNewEOA")

    def test_cancel_button(self):
        """Test pressing cancel button dismisses with None."""
        from iwa.tui.modals.base import CreateEOAModal

        modal = CreateEOAModal.__new__(CreateEOAModal)
        modal.dismiss = MagicMock()

        event = MagicMock()
        event.button.id = "cancel"
        modal.on_button_pressed(event)

        modal.dismiss.assert_called_once_with(None)


class TestCreateSafeModalButtonPress:
    """Test CreateSafeModal.on_button_pressed (lines 153-160)."""

    def test_create_button(self):
        """Test pressing create button dismisses with form data."""
        from iwa.tui.modals.base import CreateSafeModal

        modal = CreateSafeModal.__new__(CreateSafeModal)

        def query_side_effect(selector, cls=None):
            mocks = {
                "#tag_input": MagicMock(value="MySafe"),
                "#threshold_input": MagicMock(value="2"),
                "#owners_list": MagicMock(selected=["0xOwner1", "0xOwner2"]),
                "#chains_list": MagicMock(selected=["gnosis"]),
            }
            return mocks.get(selector, MagicMock())

        modal.query_one = MagicMock(side_effect=query_side_effect)
        modal.dismiss = MagicMock()

        event = MagicMock()
        event.button.id = "create"
        modal.on_button_pressed(event)

        modal.dismiss.assert_called_once()
        result = modal.dismiss.call_args[0][0]
        assert result["tag"] == "MySafe"
        assert result["threshold"] == 2
        assert result["owners"] == ["0xOwner1", "0xOwner2"]
        assert result["chains"] == ["gnosis"]

    def test_cancel_button(self):
        """Test pressing cancel button dismisses with None."""
        from iwa.tui.modals.base import CreateSafeModal

        modal = CreateSafeModal.__new__(CreateSafeModal)
        modal.dismiss = MagicMock()

        event = MagicMock()
        event.button.id = "cancel"
        modal.on_button_pressed(event)

        modal.dismiss.assert_called_once_with(None)


class TestStakeServiceModalButtonPress:
    """Test StakeServiceModal.on_button_pressed (lines 218-224)."""

    def test_stake_button_with_selection(self):
        """Test pressing stake with a valid selection."""

        from iwa.tui.modals.base import StakeServiceModal

        modal = StakeServiceModal.__new__(StakeServiceModal)
        mock_select = MagicMock()
        mock_select.value = "0xContractAddr"
        modal.query_one = MagicMock(return_value=mock_select)
        modal.dismiss = MagicMock()

        event = MagicMock()
        event.button.id = "stake"
        modal.on_button_pressed(event)

        modal.dismiss.assert_called_once_with("0xContractAddr")

    def test_stake_button_blank_selection(self):
        """Test pressing stake with BLANK selection."""
        from textual.widgets import Select

        from iwa.tui.modals.base import StakeServiceModal

        modal = StakeServiceModal.__new__(StakeServiceModal)
        mock_select = MagicMock()
        mock_select.value = Select.BLANK
        modal.query_one = MagicMock(return_value=mock_select)
        modal.dismiss = MagicMock()

        event = MagicMock()
        event.button.id = "stake"
        modal.on_button_pressed(event)

        modal.dismiss.assert_not_called()

    def test_cancel_button(self):
        """Test pressing cancel button."""
        from iwa.tui.modals.base import StakeServiceModal

        modal = StakeServiceModal.__new__(StakeServiceModal)
        modal.dismiss = MagicMock()

        event = MagicMock()
        event.button.id = "cancel"
        modal.on_button_pressed(event)

        modal.dismiss.assert_called_once_with(None)


class TestCreateServiceModalButtonPress:
    """Test CreateServiceModal.on_button_pressed (lines 307-325)."""

    def test_create_button_valid(self):
        """Test pressing create with valid form data."""

        from iwa.tui.modals.base import CreateServiceModal

        modal = CreateServiceModal.__new__(CreateServiceModal)

        def query_side_effect(selector, cls=None):
            mocks = {
                "#name_input": MagicMock(value="My Service"),
                "#chain_select": MagicMock(value="gnosis"),
                "#agent_type_select": MagicMock(value="trader"),
                "#staking_select": MagicMock(value="0xStakingAddr"),
            }
            return mocks.get(selector, MagicMock())

        modal.query_one = MagicMock(side_effect=query_side_effect)
        modal.dismiss = MagicMock()

        event = MagicMock()
        event.button.id = "create"
        modal.on_button_pressed(event)

        modal.dismiss.assert_called_once()
        result = modal.dismiss.call_args[0][0]
        assert result["name"] == "My Service"
        assert result["chain"] == "gnosis"
        assert result["agent_type"] == "trader"
        assert result["staking_contract"] == "0xStakingAddr"

    def test_create_button_no_name(self):
        """Test pressing create with no name returns early."""

        from iwa.tui.modals.base import CreateServiceModal

        modal = CreateServiceModal.__new__(CreateServiceModal)

        def query_side_effect(selector, cls=None):
            mocks = {
                "#name_input": MagicMock(value=""),
                "#chain_select": MagicMock(value="gnosis"),
                "#agent_type_select": MagicMock(value="trader"),
                "#staking_select": MagicMock(value=""),
            }
            return mocks.get(selector, MagicMock())

        modal.query_one = MagicMock(side_effect=query_side_effect)
        modal.dismiss = MagicMock()

        event = MagicMock()
        event.button.id = "create"
        modal.on_button_pressed(event)

        modal.dismiss.assert_not_called()

    def test_create_button_blank_chain(self):
        """Test pressing create with BLANK chain returns early."""
        from textual.widgets import Select

        from iwa.tui.modals.base import CreateServiceModal

        modal = CreateServiceModal.__new__(CreateServiceModal)

        def query_side_effect(selector, cls=None):
            mocks = {
                "#name_input": MagicMock(value="My Service"),
                "#chain_select": MagicMock(value=Select.BLANK),
                "#agent_type_select": MagicMock(value="trader"),
                "#staking_select": MagicMock(value=""),
            }
            return mocks.get(selector, MagicMock())

        modal.query_one = MagicMock(side_effect=query_side_effect)
        modal.dismiss = MagicMock()

        event = MagicMock()
        event.button.id = "create"
        modal.on_button_pressed(event)

        modal.dismiss.assert_not_called()

    def test_create_button_blank_agent_type(self):
        """Test create with BLANK agent_type defaults to 'trader'."""
        from textual.widgets import Select

        from iwa.tui.modals.base import CreateServiceModal

        modal = CreateServiceModal.__new__(CreateServiceModal)

        def query_side_effect(selector, cls=None):
            mocks = {
                "#name_input": MagicMock(value="My Service"),
                "#chain_select": MagicMock(value="gnosis"),
                "#agent_type_select": MagicMock(value=Select.BLANK),
                "#staking_select": MagicMock(value=Select.BLANK),
            }
            return mocks.get(selector, MagicMock())

        modal.query_one = MagicMock(side_effect=query_side_effect)
        modal.dismiss = MagicMock()

        event = MagicMock()
        event.button.id = "create"
        modal.on_button_pressed(event)

        modal.dismiss.assert_called_once()
        result = modal.dismiss.call_args[0][0]
        assert result["agent_type"] == "trader"
        assert result["staking_contract"] is None

    def test_cancel_button(self):
        """Test pressing cancel button."""
        from iwa.tui.modals.base import CreateServiceModal

        modal = CreateServiceModal.__new__(CreateServiceModal)
        modal.dismiss = MagicMock()

        event = MagicMock()
        event.button.id = "cancel"
        modal.on_button_pressed(event)

        modal.dismiss.assert_called_once_with(None)


class TestFundServiceModalButtonPress:
    """Test FundServiceModal.on_button_pressed (lines 390-406)."""

    def test_fund_button_valid_amounts(self):
        """Test pressing fund with valid amounts."""
        from iwa.tui.modals.base import FundServiceModal

        modal = FundServiceModal.__new__(FundServiceModal)
        modal.service_key = "gnosis:1"

        def query_side_effect(selector, cls=None):
            mocks = {
                "#agent_amount": MagicMock(value="1.5"),
                "#safe_amount": MagicMock(value="2.5"),
            }
            return mocks.get(selector, MagicMock())

        modal.query_one = MagicMock(side_effect=query_side_effect)
        modal.dismiss = MagicMock()

        event = MagicMock()
        event.button.id = "fund"
        modal.on_button_pressed(event)

        modal.dismiss.assert_called_once()
        result = modal.dismiss.call_args[0][0]
        assert result["service_key"] == "gnosis:1"
        assert result["agent_amount"] == 1.5
        assert result["safe_amount"] == 2.5

    def test_fund_button_zero_amounts(self):
        """Test pressing fund with zero amounts returns early."""
        from iwa.tui.modals.base import FundServiceModal

        modal = FundServiceModal.__new__(FundServiceModal)
        modal.service_key = "gnosis:1"

        def query_side_effect(selector, cls=None):
            mocks = {
                "#agent_amount": MagicMock(value="0"),
                "#safe_amount": MagicMock(value="0"),
            }
            return mocks.get(selector, MagicMock())

        modal.query_one = MagicMock(side_effect=query_side_effect)
        modal.dismiss = MagicMock()

        event = MagicMock()
        event.button.id = "fund"
        modal.on_button_pressed(event)

        modal.dismiss.assert_not_called()

    def test_fund_button_invalid_value(self):
        """Test pressing fund with non-numeric value."""
        from iwa.tui.modals.base import FundServiceModal

        modal = FundServiceModal.__new__(FundServiceModal)
        modal.service_key = "gnosis:1"

        def query_side_effect(selector, cls=None):
            mocks = {
                "#agent_amount": MagicMock(value="not_a_number"),
                "#safe_amount": MagicMock(value="also_bad"),
            }
            return mocks.get(selector, MagicMock())

        modal.query_one = MagicMock(side_effect=query_side_effect)
        modal.dismiss = MagicMock()

        event = MagicMock()
        event.button.id = "fund"
        modal.on_button_pressed(event)

        modal.dismiss.assert_not_called()

    def test_fund_button_empty_values(self):
        """Test pressing fund with empty values (defaults to 0)."""
        from iwa.tui.modals.base import FundServiceModal

        modal = FundServiceModal.__new__(FundServiceModal)
        modal.service_key = "gnosis:1"

        def query_side_effect(selector, cls=None):
            mocks = {
                "#agent_amount": MagicMock(value=""),
                "#safe_amount": MagicMock(value=""),
            }
            return mocks.get(selector, MagicMock())

        modal.query_one = MagicMock(side_effect=query_side_effect)
        modal.dismiss = MagicMock()

        event = MagicMock()
        event.button.id = "fund"
        modal.on_button_pressed(event)

        # Empty defaults to "0" -> 0.0 -> both <= 0 -> early return
        modal.dismiss.assert_not_called()

    def test_cancel_button(self):
        """Test pressing cancel button."""
        from iwa.tui.modals.base import FundServiceModal

        modal = FundServiceModal.__new__(FundServiceModal)
        modal.dismiss = MagicMock()

        event = MagicMock()
        event.button.id = "cancel"
        modal.on_button_pressed(event)

        modal.dismiss.assert_called_once_with(None)

    def test_fund_button_agent_only(self):
        """Test pressing fund with only agent amount."""
        from iwa.tui.modals.base import FundServiceModal

        modal = FundServiceModal.__new__(FundServiceModal)
        modal.service_key = "gnosis:1"

        def query_side_effect(selector, cls=None):
            mocks = {
                "#agent_amount": MagicMock(value="1.0"),
                "#safe_amount": MagicMock(value="0"),
            }
            return mocks.get(selector, MagicMock())

        modal.query_one = MagicMock(side_effect=query_side_effect)
        modal.dismiss = MagicMock()

        event = MagicMock()
        event.button.id = "fund"
        modal.on_button_pressed(event)

        modal.dismiss.assert_called_once()
        result = modal.dismiss.call_args[0][0]
        assert result["agent_amount"] == 1.0
        assert result["safe_amount"] == 0.0
