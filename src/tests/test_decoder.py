"""Comprehensive tests for iwa.core.contracts.decoder.ErrorDecoder."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest
from eth_abi import encode
from web3 import Web3

from iwa.core.contracts.decoder import (
    ERROR_SELECTOR,
    PANIC_CODES,
    PANIC_SELECTOR,
    ErrorDecoder,
)


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset ErrorDecoder singleton before each test so tests are isolated."""
    ErrorDecoder._instance = None
    ErrorDecoder._selectors = {}
    ErrorDecoder._initialized = False
    yield
    ErrorDecoder._instance = None
    ErrorDecoder._selectors = {}
    ErrorDecoder._initialized = False


@pytest.fixture
def decoder():
    """Create an ErrorDecoder with load_all_abis mocked out (no filesystem access)."""
    with patch.object(ErrorDecoder, "load_all_abis"):
        d = ErrorDecoder()
    return d


# =============================================================================
# Singleton pattern tests
# =============================================================================


class TestSingleton:
    """Test that ErrorDecoder follows the singleton pattern."""

    def test_singleton_returns_same_instance(self):
        """Two calls to ErrorDecoder() return the same object."""
        with patch.object(ErrorDecoder, "load_all_abis"):
            d1 = ErrorDecoder()
            d2 = ErrorDecoder()
        assert d1 is d2

    def test_singleton_only_initializes_once(self):
        """load_all_abis is called only on the first instantiation."""
        with patch.object(ErrorDecoder, "load_all_abis") as mock_load:
            ErrorDecoder()
            ErrorDecoder()
        mock_load.assert_called_once()


# =============================================================================
# load_all_abis tests
# =============================================================================


def _make_fake_src_root(tmpdir):
    """Build a fake src root with the decoder at the expected depth.

    load_all_abis does:
        Path(__file__).resolve().parents[3]   ->  src_root

    So we need __file__ to be at depth 4 under tmpdir:
        tmpdir / a / b / c / decoder.py   ->  parents[3] = tmpdir
    """
    fake_file = Path(tmpdir) / "a" / "b" / "c" / "decoder.py"
    fake_file.parent.mkdir(parents=True, exist_ok=True)
    fake_file.touch()
    return fake_file


class TestLoadAllAbis:
    """Test ABI file discovery and loading by actually calling load_all_abis."""

    def test_loads_abi_as_list(self):
        """ABI files containing a JSON array are loaded and errors registered."""
        with tempfile.TemporaryDirectory() as tmpdir:
            abis_dir = Path(tmpdir) / "pkg" / "contracts" / "abis"
            abis_dir.mkdir(parents=True)
            (abis_dir / "token.json").write_text(json.dumps([
                {
                    "type": "error",
                    "name": "InsufficientBalance",
                    "inputs": [{"type": "uint256", "name": "available"}],
                }
            ]))

            fake_file = _make_fake_src_root(tmpdir)

            d = ErrorDecoder.__new__(ErrorDecoder)
            d._selectors = {}
            d._initialized = False

            with patch("iwa.core.contracts.decoder.__file__", str(fake_file)):
                d.load_all_abis()

            assert len(d._selectors) == 1

    def test_loads_abi_as_dict_with_abi_key(self):
        """ABI files containing a dict with 'abi' key are unwrapped correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            abis_dir = Path(tmpdir) / "pkg" / "contracts" / "abis"
            abis_dir.mkdir(parents=True)
            (abis_dir / "auth.json").write_text(json.dumps({
                "abi": [
                    {"type": "error", "name": "Unauthorized", "inputs": []},
                ]
            }))

            fake_file = _make_fake_src_root(tmpdir)

            d = ErrorDecoder.__new__(ErrorDecoder)
            d._selectors = {}
            d._initialized = False

            with patch("iwa.core.contracts.decoder.__file__", str(fake_file)):
                d.load_all_abis()

            assert len(d._selectors) == 1

    def test_skips_non_list_abi_content(self):
        """If the loaded content is a dict without 'abi', it is not a list -> skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            abis_dir = Path(tmpdir) / "pkg" / "contracts" / "abis"
            abis_dir.mkdir(parents=True)
            # File whose content is a dict without "abi" key
            (abis_dir / "notabi.json").write_text(json.dumps(
                {"name": "not_an_abi", "version": "1.0"}
            ))

            fake_file = _make_fake_src_root(tmpdir)

            d = ErrorDecoder.__new__(ErrorDecoder)
            d._selectors = {}
            d._initialized = False

            with patch("iwa.core.contracts.decoder.__file__", str(fake_file)):
                d.load_all_abis()

            # No errors found since content is not a list
            assert len(d._selectors) == 0

    def test_handles_malformed_json_gracefully(self):
        """Files with invalid JSON are skipped with a warning log."""
        with tempfile.TemporaryDirectory() as tmpdir:
            abis_dir = Path(tmpdir) / "pkg" / "contracts" / "abis"
            abis_dir.mkdir(parents=True)
            (abis_dir / "bad.json").write_text("{ not valid json !!!")

            fake_file = _make_fake_src_root(tmpdir)

            d = ErrorDecoder.__new__(ErrorDecoder)
            d._selectors = {}
            d._initialized = False

            with (
                patch("iwa.core.contracts.decoder.__file__", str(fake_file)),
                patch("iwa.core.contracts.decoder.logger") as mock_logger,
            ):
                d.load_all_abis()

            mock_logger.warning.assert_called_once()
            assert len(d._selectors) == 0

    def test_load_all_abis_good_and_bad_files(self):
        """Good ABI files are loaded while bad ones are skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            abis_dir = Path(tmpdir) / "pkg" / "contracts" / "abis"
            abis_dir.mkdir(parents=True)

            (abis_dir / "good.json").write_text(json.dumps([
                {"type": "error", "name": "TestError", "inputs": []}
            ]))
            (abis_dir / "bad.json").write_text("NOT JSON")

            fake_file = _make_fake_src_root(tmpdir)

            d = ErrorDecoder.__new__(ErrorDecoder)
            d._selectors = {}
            d._initialized = False

            with (
                patch("iwa.core.contracts.decoder.__file__", str(fake_file)),
                patch("iwa.core.contracts.decoder.logger") as mock_logger,
            ):
                d.load_all_abis()

            # Good file was processed, bad file was skipped with warning
            assert len(d._selectors) == 1
            mock_logger.warning.assert_called_once()

    def test_core_abi_path_already_discovered(self):
        """Core ABI path does not add duplicates when already found by main glob."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # The glob **/contracts/abis/*.json will find this
            core_abis_dir = Path(tmpdir) / "iwa" / "core" / "contracts" / "abis"
            core_abis_dir.mkdir(parents=True)
            (core_abis_dir / "core_error.json").write_text(json.dumps([
                {"type": "error", "name": "CoreError", "inputs": []}
            ]))

            fake_file = _make_fake_src_root(tmpdir)

            d = ErrorDecoder.__new__(ErrorDecoder)
            d._selectors = {}
            d._initialized = False

            with patch("iwa.core.contracts.decoder.__file__", str(fake_file)):
                d.load_all_abis()

            # Only one error registered (no duplicate from fallback)
            selector = "0x" + Web3.keccak(text="CoreError()")[:4].hex()
            assert len(d._selectors[selector]) == 1

    def test_core_abi_path_adds_when_not_in_glob(self):
        """Core ABI path adds files when main glob found files in other dirs only."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a non-core abis dir that the main glob will find
            other_abis_dir = Path(tmpdir) / "plugins" / "contracts" / "abis"
            other_abis_dir.mkdir(parents=True)
            (other_abis_dir / "plugin.json").write_text(json.dumps([
                {"type": "error", "name": "PluginError", "inputs": []}
            ]))

            # Create core abis dir separately
            core_abis_dir = Path(tmpdir) / "iwa" / "core" / "contracts" / "abis"
            core_abis_dir.mkdir(parents=True)
            (core_abis_dir / "core.json").write_text(json.dumps([
                {"type": "error", "name": "CoreOnly", "inputs": []}
            ]))

            fake_file = _make_fake_src_root(tmpdir)

            d = ErrorDecoder.__new__(ErrorDecoder)
            d._selectors = {}
            d._initialized = False

            with patch("iwa.core.contracts.decoder.__file__", str(fake_file)):
                d.load_all_abis()

            # Both errors should be registered
            assert len(d._selectors) == 2

    def test_no_abi_files_found(self):
        """When no ABI files exist, no errors are registered."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_file = _make_fake_src_root(tmpdir)

            d = ErrorDecoder.__new__(ErrorDecoder)
            d._selectors = {}
            d._initialized = False

            with patch("iwa.core.contracts.decoder.__file__", str(fake_file)):
                d.load_all_abis()

            assert len(d._selectors) == 0


# =============================================================================
# _process_abi tests
# =============================================================================


class TestProcessAbi:
    """Test ABI error extraction and selector computation."""

    def test_extracts_error_entries_only(self, decoder):
        """Only 'error' type entries are processed, not functions or events."""
        abi = [
            {"type": "function", "name": "transfer", "inputs": []},
            {"type": "event", "name": "Transfer", "inputs": []},
            {
                "type": "error",
                "name": "InsufficientBalance",
                "inputs": [{"type": "uint256", "name": "balance"}],
            },
        ]
        decoder._process_abi(abi, "test.json")

        assert len(decoder._selectors) == 1
        entries = list(decoder._selectors.values())[0]
        assert entries[0]["name"] == "InsufficientBalance"

    def test_computes_correct_selector(self, decoder):
        """Selector is the first 4 bytes of keccak256 of the signature."""
        abi = [
            {
                "type": "error",
                "name": "Unauthorized",
                "inputs": [],
            }
        ]
        decoder._process_abi(abi, "test.json")

        expected_selector = "0x" + Web3.keccak(text="Unauthorized()")[:4].hex()
        assert expected_selector in decoder._selectors

    def test_selector_with_multiple_params(self, decoder):
        """Selector is computed correctly for errors with multiple parameters."""
        abi = [
            {
                "type": "error",
                "name": "TransferFailed",
                "inputs": [
                    {"type": "address", "name": "from"},
                    {"type": "address", "name": "to"},
                    {"type": "uint256", "name": "amount"},
                ],
            }
        ]
        decoder._process_abi(abi, "test.json")

        expected_selector = "0x" + Web3.keccak(
            text="TransferFailed(address,address,uint256)"
        )[:4].hex()
        assert expected_selector in decoder._selectors

        entry = decoder._selectors[expected_selector][0]
        assert entry["types"] == ["address", "address", "uint256"]
        assert entry["arg_names"] == ["from", "to", "amount"]
        assert entry["source"] == "test.json"
        assert entry["signature"] == "TransferFailed(address,address,uint256)"

    def test_deduplication(self, decoder):
        """Same error from two different sources is not duplicated."""
        abi = [
            {
                "type": "error",
                "name": "Unauthorized",
                "inputs": [],
            }
        ]
        # Process the same ABI twice with the same source name
        decoder._process_abi(abi, "test.json")
        decoder._process_abi(abi, "test.json")

        selector = "0x" + Web3.keccak(text="Unauthorized()")[:4].hex()
        assert len(decoder._selectors[selector]) == 1

    def test_same_selector_different_sources_both_kept(self, decoder):
        """Same error signature from different source files -> both kept if different."""
        abi = [
            {"type": "error", "name": "Unauthorized", "inputs": []}
        ]
        decoder._process_abi(abi, "source_a.json")
        decoder._process_abi(abi, "source_b.json")

        selector = "0x" + Web3.keccak(text="Unauthorized()")[:4].hex()
        # The decoding dicts differ because "source" is different
        assert len(decoder._selectors[selector]) == 2

    def test_error_with_no_inputs(self, decoder):
        """Error with no inputs field defaults to empty lists."""
        abi = [
            {"type": "error", "name": "Paused"},  # No "inputs" key at all
        ]
        decoder._process_abi(abi, "test.json")

        selector = "0x" + Web3.keccak(text="Paused()")[:4].hex()
        assert selector in decoder._selectors
        entry = decoder._selectors[selector][0]
        assert entry["types"] == []
        assert entry["arg_names"] == []

    def test_multiple_errors_in_one_abi(self, decoder):
        """Multiple error types in a single ABI are all registered."""
        abi = [
            {"type": "error", "name": "ErrorA", "inputs": []},
            {"type": "error", "name": "ErrorB", "inputs": [{"type": "uint256", "name": "x"}]},
            {"type": "error", "name": "ErrorC", "inputs": [{"type": "address", "name": "a"}]},
        ]
        decoder._process_abi(abi, "test.json")

        assert len(decoder._selectors) == 3


# =============================================================================
# decode() tests
# =============================================================================


class TestDecode:
    """Test the decode method with various error data formats."""

    # -- Edge cases: empty / malformed input --

    def test_empty_string_returns_empty(self, decoder):
        """Empty error data returns empty list."""
        assert decoder.decode("") == []

    def test_none_returns_empty(self, decoder):
        """None-ish input returns empty list."""
        assert decoder.decode(None) == []

    def test_too_short_data_returns_empty(self, decoder):
        """Data shorter than 10 chars (4-byte selector) returns empty list."""
        assert decoder.decode("0x1234") == []
        assert decoder.decode("0x12345") == []
        assert decoder.decode("0x123456") == []
        assert decoder.decode("0x1234567") == []
        assert decoder.decode("0x12345678") == []  # Exactly 10 chars -> selector only

    def test_adds_0x_prefix_if_missing(self, decoder):
        """If error data lacks 0x prefix, it is added automatically."""
        # Build a valid Error(string) to test prefix addition
        encoded_str = encode(["string"], ["test message"]).hex()
        data_no_prefix = ERROR_SELECTOR[2:] + encoded_str  # Remove 0x from selector

        result = decoder.decode(data_no_prefix)
        assert len(result) == 1
        assert result[0][0] == "Error"
        assert "test message" in result[0][1]

    # -- Standard Error(string) decoding --

    def test_decode_standard_error_string(self, decoder):
        """Standard Solidity Error(string) is decoded correctly."""
        message = "Insufficient funds"
        encoded_args = encode(["string"], [message]).hex()
        error_data = ERROR_SELECTOR + encoded_args

        result = decoder.decode(error_data)

        assert len(result) == 1
        name, msg, source = result[0]
        assert name == "Error"
        assert message in msg
        assert source == "Built-in"

    def test_decode_error_string_empty_message(self, decoder):
        """Error(string) with an empty string still decodes."""
        encoded_args = encode(["string"], [""]).hex()
        error_data = ERROR_SELECTOR + encoded_args

        result = decoder.decode(error_data)
        assert len(result) == 1
        assert result[0][0] == "Error"

    def test_decode_error_string_malformed_data(self, decoder):
        """Error(string) with corrupted data doesn't crash, returns empty."""
        # Selector is correct but payload is garbage
        error_data = ERROR_SELECTOR + "deadbeef"

        result = decoder.decode(error_data)
        # The decode will raise, the except catches it, result stays empty
        assert result == []

    # -- Panic(uint256) decoding --

    def test_decode_panic_known_code(self, decoder):
        """Panic with a known code returns the human-readable message."""
        for code, expected_msg in PANIC_CODES.items():
            encoded_args = encode(["uint256"], [code]).hex()
            error_data = PANIC_SELECTOR + encoded_args

            result = decoder.decode(error_data)

            assert len(result) == 1
            name, msg, source = result[0]
            assert name == "Panic"
            assert expected_msg in msg
            assert source == "Built-in"

    def test_decode_panic_unknown_code(self, decoder):
        """Panic with an unknown code shows 'Unknown panic code N'."""
        unknown_code = 0xFF
        encoded_args = encode(["uint256"], [unknown_code]).hex()
        error_data = PANIC_SELECTOR + encoded_args

        result = decoder.decode(error_data)

        assert len(result) == 1
        assert "Unknown panic code" in result[0][1]

    def test_decode_panic_malformed_data(self, decoder):
        """Panic with corrupted payload doesn't crash."""
        error_data = PANIC_SELECTOR + "badc0de"

        result = decoder.decode(error_data)
        assert result == []

    # -- Custom error decoding --

    def test_decode_custom_error_no_args(self, decoder):
        """Custom error with no arguments decodes correctly."""
        abi = [{"type": "error", "name": "Paused", "inputs": []}]
        decoder._process_abi(abi, "protocol.json")

        selector = "0x" + Web3.keccak(text="Paused()")[:4].hex()
        error_data = selector  # No encoded args needed

        result = decoder.decode(error_data)

        assert len(result) == 1
        name, msg, source = result[0]
        assert name == "Paused"
        assert "Paused()" == msg
        assert source == "protocol.json"

    def test_decode_custom_error_with_args(self, decoder):
        """Custom error with arguments decodes values correctly."""
        abi = [
            {
                "type": "error",
                "name": "InsufficientBalance",
                "inputs": [
                    {"type": "uint256", "name": "available"},
                    {"type": "uint256", "name": "required"},
                ],
            }
        ]
        decoder._process_abi(abi, "token.json")

        selector = "0x" + Web3.keccak(
            text="InsufficientBalance(uint256,uint256)"
        )[:4].hex()
        encoded_args = encode(["uint256", "uint256"], [100, 500]).hex()
        error_data = selector + encoded_args

        result = decoder.decode(error_data)

        assert len(result) == 1
        name, msg, source = result[0]
        assert name == "InsufficientBalance"
        assert "available=100" in msg
        assert "required=500" in msg
        assert source == "token.json"

    def test_decode_custom_error_with_address_arg(self, decoder):
        """Custom error with an address argument decodes correctly."""
        abi = [
            {
                "type": "error",
                "name": "UnauthorizedCaller",
                "inputs": [{"type": "address", "name": "caller"}],
            }
        ]
        decoder._process_abi(abi, "access.json")

        addr = "0x78731D3Ca6b7E34aC0F824c42a7cC18A495cabaB"
        selector = "0x" + Web3.keccak(text="UnauthorizedCaller(address)")[:4].hex()
        encoded_args = encode(["address"], [addr]).hex()
        error_data = selector + encoded_args

        result = decoder.decode(error_data)

        assert len(result) == 1
        assert "UnauthorizedCaller" in result[0][1]
        # Address is checksummed in the decoded output
        assert addr.lower() in result[0][1].lower()

    def test_decode_custom_error_malformed_args(self, decoder):
        """Custom error with corrupted args is silently skipped (continue)."""
        abi = [
            {
                "type": "error",
                "name": "BadError",
                "inputs": [{"type": "uint256", "name": "x"}],
            }
        ]
        decoder._process_abi(abi, "test.json")

        selector = "0x" + Web3.keccak(text="BadError(uint256)")[:4].hex()
        # Provide garbage data that can't decode as uint256
        error_data = selector + "deadbeef"

        result = decoder.decode(error_data)
        # The decode fails silently (continue), result is empty
        assert result == []

    def test_decode_unknown_selector_returns_empty(self, decoder):
        """An unknown selector that doesn't match any registered error returns empty."""
        error_data = "0xdeadbeef" + "00" * 32

        result = decoder.decode(error_data)
        assert result == []

    def test_decode_multiple_possible_decodings(self, decoder):
        """When multiple decodings match the same selector, all are returned."""
        # Register two different errors from different sources with the same selector
        # (This is artificial but tests the loop on line 149)
        abi_a = [{"type": "error", "name": "ErrorA", "inputs": []}]
        abi_b = [{"type": "error", "name": "ErrorA", "inputs": []}]
        decoder._process_abi(abi_a, "source_a.json")
        decoder._process_abi(abi_b, "source_b.json")

        selector = "0x" + Web3.keccak(text="ErrorA()")[:4].hex()
        error_data = selector

        result = decoder.decode(error_data)
        assert len(result) == 2
        sources = {r[2] for r in result}
        assert "source_a.json" in sources
        assert "source_b.json" in sources

    def test_decode_selector_is_lowercased_for_matching(self, decoder):
        """Selector matching is case-insensitive (lowercased)."""
        abi = [{"type": "error", "name": "TestError", "inputs": []}]
        decoder._process_abi(abi, "test.json")

        selector = "0x" + Web3.keccak(text="TestError()")[:4].hex()
        # Use uppercase hex in error_data
        upper_data = selector.upper().replace("0X", "0x")

        result = decoder.decode(upper_data)
        # Since decode lowercases the selector, but _process_abi stores lowercase too
        # (Web3.keccak returns lowercase hex), this should match
        assert len(result) == 1

    def test_decode_with_exactly_10_chars(self, decoder):
        """Data with exactly 10 chars (selector only, no args) works for no-arg errors."""
        abi = [{"type": "error", "name": "EmptyError", "inputs": []}]
        decoder._process_abi(abi, "test.json")

        selector = "0x" + Web3.keccak(text="EmptyError()")[:4].hex()
        # selector is exactly 10 chars (0x + 8 hex chars)
        assert len(selector) == 10

        result = decoder.decode(selector)
        assert len(result) == 1
        assert result[0][0] == "EmptyError"

    # -- Combined scenarios --

    def test_decode_standard_error_does_not_check_custom(self, decoder):
        """Standard Error(string) does NOT also check custom errors unless selector matches."""
        # Register a custom error — its selector won't be ERROR_SELECTOR
        abi = [{"type": "error", "name": "Custom", "inputs": []}]
        decoder._process_abi(abi, "test.json")

        # Build a standard Error(string)
        encoded = encode(["string"], ["hello"]).hex()
        error_data = ERROR_SELECTOR + encoded

        result = decoder.decode(error_data)
        # Only the standard Error should be returned
        assert len(result) == 1
        assert result[0][0] == "Error"

    def test_decode_multiple_decodings_with_one_failing(self, decoder):
        """When one decoding fails but another succeeds, the successful one is returned."""
        # Register two decodings for the same selector but with different types.
        # One will fail to decode while the other succeeds.
        selector = "0x" + Web3.keccak(text="MultiError(uint256)")[:4].hex()

        decoder._selectors[selector] = [
            {
                "name": "MultiError",
                "types": ["uint256", "uint256"],  # Wrong arity -- will fail
                "arg_names": ["a", "b"],
                "source": "bad_source.json",
                "signature": "MultiError(uint256,uint256)",
            },
            {
                "name": "MultiError",
                "types": ["uint256"],  # Correct -- will succeed
                "arg_names": ["a"],
                "source": "good_source.json",
                "signature": "MultiError(uint256)",
            },
        ]

        encoded_args = encode(["uint256"], [42]).hex()
        error_data = selector + encoded_args

        result = decoder.decode(error_data)
        # Only the successful decoding should appear
        assert len(result) == 1
        assert result[0][2] == "good_source.json"
        assert "a=42" in result[0][1]


# =============================================================================
# Constants tests
# =============================================================================


class TestConstants:
    """Verify that module-level constants are correct."""

    def test_error_selector_value(self):
        """ERROR_SELECTOR matches keccak256 of 'Error(string)'."""
        expected = "0x" + Web3.keccak(text="Error(string)")[:4].hex()
        assert ERROR_SELECTOR == expected

    def test_panic_selector_value(self):
        """PANIC_SELECTOR matches keccak256 of 'Panic(uint256)'."""
        expected = "0x" + Web3.keccak(text="Panic(uint256)")[:4].hex()
        assert PANIC_SELECTOR == expected

    def test_panic_codes_has_known_entries(self):
        """PANIC_CODES contains the standard Solidity panic codes."""
        assert 0x00 in PANIC_CODES
        assert 0x01 in PANIC_CODES
        assert 0x11 in PANIC_CODES
        assert 0x12 in PANIC_CODES
        assert 0x21 in PANIC_CODES
        assert 0x22 in PANIC_CODES
        assert 0x31 in PANIC_CODES
        assert 0x32 in PANIC_CODES
        assert 0x41 in PANIC_CODES
        assert 0x51 in PANIC_CODES


# =============================================================================
# Integration-style test
# =============================================================================


class TestIntegration:
    """End-to-end style tests that exercise multiple components together."""

    def test_process_abi_then_decode_roundtrip(self, decoder):
        """Register a custom error via _process_abi, then decode data for it."""
        abi = [
            {
                "type": "error",
                "name": "SlippageTooHigh",
                "inputs": [
                    {"type": "uint256", "name": "expected"},
                    {"type": "uint256", "name": "actual"},
                ],
            }
        ]
        decoder._process_abi(abi, "dex.json")

        expected_val = 1000
        actual_val = 900
        selector = "0x" + Web3.keccak(
            text="SlippageTooHigh(uint256,uint256)"
        )[:4].hex()
        encoded = encode(["uint256", "uint256"], [expected_val, actual_val]).hex()
        error_data = selector + encoded

        result = decoder.decode(error_data)

        assert len(result) == 1
        assert result[0][0] == "SlippageTooHigh"
        assert f"expected={expected_val}" in result[0][1]
        assert f"actual={actual_val}" in result[0][1]
        assert result[0][2] == "dex.json"

    def test_all_three_types_together(self, decoder):
        """Demonstrates that standard Error, Panic, and custom errors all work."""
        # Register a custom error
        abi = [{"type": "error", "name": "CustomRevert", "inputs": []}]
        decoder._process_abi(abi, "test.json")

        # Decode standard Error(string)
        err_encoded = encode(["string"], ["fail"]).hex()
        err_result = decoder.decode(ERROR_SELECTOR + err_encoded)
        assert err_result[0][0] == "Error"

        # Decode Panic(uint256)
        panic_encoded = encode(["uint256"], [0x01]).hex()
        panic_result = decoder.decode(PANIC_SELECTOR + panic_encoded)
        assert panic_result[0][0] == "Panic"

        # Decode custom error
        custom_selector = "0x" + Web3.keccak(text="CustomRevert()")[:4].hex()
        custom_result = decoder.decode(custom_selector)
        assert custom_result[0][0] == "CustomRevert"
