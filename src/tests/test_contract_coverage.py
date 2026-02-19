"""Tests to improve coverage for iwa.core.contracts.contract module.

Targets uncovered lines: 67-68, 133, 137, 140, 154-156, 163-165,
169-176, 183-186, 207-209, 214, 246-256, 266, 269-271, 332.
"""

from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest
from web3.exceptions import ContractCustomError

from iwa.core.contracts.contract import (
    ContractInstance,
    _ABI_CACHE,
    clear_abi_cache,
)

# Valid 42-char Ethereum addresses
ADDR_A = "0x1111111111111111111111111111111111111111"
ADDR_B = "0x2222222222222222222222222222222222222222"

# Standard ABI with function, error, and event entries
STANDARD_ABI = (
    '[{"type": "function", "name": "testFunc", "inputs": []},'
    ' {"type": "error", "name": "CustomError", "inputs": [{"type": "uint256", "name": "code"}]},'
    ' {"type": "event", "name": "TestEvent", "inputs": []}]'
)


@pytest.fixture(autouse=True)
def clean_abi_cache():
    """Clear global ABI cache before and after each test."""
    clear_abi_cache()
    yield
    clear_abi_cache()


@pytest.fixture
def mock_chain_interface():
    with patch("iwa.core.contracts.contract.ChainInterfaces") as mock:
        mock_ci = mock.return_value.get.return_value
        mock_ci.web3._web3.eth.contract.return_value = MagicMock()
        yield mock_ci


@pytest.fixture
def mock_abi_file():
    with patch("builtins.open", mock_open(read_data=STANDARD_ABI)):
        yield


class MockContract(ContractInstance):
    name = "test_contract"
    abi_path = Path("test.json")


# ---------------------------------------------------------------------------
# Lines 67-68: ABI cache hit path
# ---------------------------------------------------------------------------
class TestABICacheHit:
    def test_second_init_uses_cache(self, mock_chain_interface, mock_abi_file):
        """Second instantiation should hit the ABI cache (lines 67-68)."""
        contract1 = MockContract(ADDR_A, "gnosis")
        assert contract1.abi is not None

        # Second instantiation should NOT open the file — it should use cache
        with patch("builtins.open", side_effect=AssertionError("should not open file")):
            contract2 = MockContract(ADDR_A, "gnosis")

        assert contract2.abi == contract1.abi
        assert contract2.error_selectors == contract1.error_selectors


# ---------------------------------------------------------------------------
# Lines 133, 137, 140: decode_error edge cases
# ---------------------------------------------------------------------------
class TestDecodeErrorEdgeCases:
    def test_decode_error_empty_data(self, mock_chain_interface, mock_abi_file):
        """Empty string returns None (line 133)."""
        contract = MockContract(ADDR_A, "gnosis")
        assert contract.decode_error("") is None
        assert contract.decode_error(None) is None

    def test_decode_error_no_0x_prefix(self, mock_chain_interface, mock_abi_file):
        """Data without 0x prefix gets normalized (line 137)."""
        contract = MockContract(ADDR_A, "gnosis")
        # Short data without prefix — after normalization "0x" + "1234" => len 6 < 10
        result = contract.decode_error("1234")
        assert result is None

    def test_decode_error_short_data(self, mock_chain_interface, mock_abi_file):
        """Data shorter than 10 chars returns None (line 140)."""
        contract = MockContract(ADDR_A, "gnosis")
        assert contract.decode_error("0x1234") is None
        assert contract.decode_error("0x123456") is None


# ---------------------------------------------------------------------------
# Lines 154-156: Custom error decode failure
# ---------------------------------------------------------------------------
class TestCustomErrorDecodeFail:
    def test_custom_error_args_decode_failure(self, mock_chain_interface, mock_abi_file):
        """When eth_abi.decode fails for custom error, return name with 'decoding failed' (lines 154-156)."""
        contract = MockContract(ADDR_A, "gnosis")
        selector = list(contract.error_selectors.keys())[0]
        # Provide invalid encoded args — too short to decode as uint256
        bad_encoded = "deadbeef"
        error_data = f"{selector}{bad_encoded}"
        result = contract.decode_error(error_data)
        assert result is not None
        assert result[0] == "CustomError"
        assert "decoding failed" in result[1]


# ---------------------------------------------------------------------------
# Lines 163-165: Standard Error(string) decode failure
# ---------------------------------------------------------------------------
class TestStandardErrorDecodeFail:
    def test_error_string_decode_failure(self, mock_chain_interface, mock_abi_file):
        """When Error(string) decode fails, return fallback message (lines 163-165)."""
        contract = MockContract(ADDR_A, "gnosis")
        # Use the Error(string) selector with invalid encoded data
        error_data = "0x08c379a0" + "deadbeef"
        result = contract.decode_error(error_data)
        assert result is not None
        assert result[0] == "Error"
        assert result[1] == "Failed to decode error message"


# ---------------------------------------------------------------------------
# Lines 169-176: Panic(uint256) decoding
# ---------------------------------------------------------------------------
class TestPanicDecoding:
    def test_panic_known_code(self, mock_chain_interface, mock_abi_file):
        """Panic with known code returns description (lines 169-173)."""
        contract = MockContract(ADDR_A, "gnosis")
        # Panic selector + uint256(0x01) = Assert failed
        panic_selector = "0x4e487b71"
        # uint256(1) encoded as 32 bytes
        encoded_code = "0" * 63 + "1"
        error_data = f"{panic_selector}{encoded_code}"
        result = contract.decode_error(error_data)
        assert result is not None
        assert result[0] == "Panic"
        assert "Assert failed" in result[1]

    def test_panic_unknown_code(self, mock_chain_interface, mock_abi_file):
        """Panic with unknown code returns 'Unknown panic code' (line 172)."""
        contract = MockContract(ADDR_A, "gnosis")
        panic_selector = "0x4e487b71"
        # uint256(0xFF) — not in PANIC_CODES
        encoded_code = "0" * 62 + "ff"
        error_data = f"{panic_selector}{encoded_code}"
        result = contract.decode_error(error_data)
        assert result is not None
        assert result[0] == "Panic"
        assert "Unknown panic code" in result[1]

    def test_panic_decode_failure(self, mock_chain_interface, mock_abi_file):
        """When Panic decode fails, return fallback (lines 175-176)."""
        contract = MockContract(ADDR_A, "gnosis")
        panic_selector = "0x4e487b71"
        # Invalid data — too short
        error_data = f"{panic_selector}deadbeef"
        result = contract.decode_error(error_data)
        assert result is not None
        assert result[0] == "Panic"
        assert result[1] == "Failed to decode panic code"


# ---------------------------------------------------------------------------
# Lines 183-186: Global fallback decoder
# ---------------------------------------------------------------------------
class TestGlobalFallbackDecoder:
    def test_global_decoder_finds_match(self, mock_chain_interface, mock_abi_file):
        """Global ErrorDecoder returns results for unknown selector (lines 183-184)."""
        contract = MockContract(ADDR_A, "gnosis")
        unknown_selector = "0xaabbccdd"
        # Enough data to be a valid error
        encoded = "0" * 64
        error_data = f"{unknown_selector}{encoded}"

        with patch("iwa.core.contracts.contract.ErrorDecoder") as mock_decoder_cls:
            mock_decoder = mock_decoder_cls.return_value
            mock_decoder.decode.return_value = [("SomeError", "SomeError(val=42)", {})]
            result = contract.decode_error(error_data)

        assert result is not None
        assert result[0] == "SomeError"
        assert result[1] == "SomeError(val=42)"

    def test_global_decoder_no_match(self, mock_chain_interface, mock_abi_file):
        """Global ErrorDecoder returns empty list — final None (line 188)."""
        contract = MockContract(ADDR_A, "gnosis")
        unknown_selector = "0xaabbccdd"
        encoded = "0" * 64
        error_data = f"{unknown_selector}{encoded}"

        with patch("iwa.core.contracts.contract.ErrorDecoder") as mock_decoder_cls:
            mock_decoder = mock_decoder_cls.return_value
            mock_decoder.decode.return_value = []
            result = contract.decode_error(error_data)

        assert result is None

    def test_global_decoder_exception(self, mock_chain_interface, mock_abi_file):
        """Global ErrorDecoder raises exception — falls through to None (lines 185-186)."""
        contract = MockContract(ADDR_A, "gnosis")
        unknown_selector = "0xaabbccdd"
        encoded = "0" * 64
        error_data = f"{unknown_selector}{encoded}"

        with patch("iwa.core.contracts.contract.ErrorDecoder") as mock_decoder_cls:
            mock_decoder = mock_decoder_cls.return_value
            mock_decoder.decode.side_effect = RuntimeError("decoder broken")
            result = contract.decode_error(error_data)

        assert result is None


# ---------------------------------------------------------------------------
# Lines 207-209: _extract_error_data dict arg with data key
# ---------------------------------------------------------------------------
class TestExtractErrorDataDict:
    def test_dict_arg_with_hex_data(self, mock_chain_interface, mock_abi_file):
        """Exception arg is dict with data key containing hex (lines 207-209)."""
        contract = MockContract(ADDR_A, "gnosis")
        exc = Exception({"data": "0xdeadbeef1234567890"})
        result = contract._extract_error_data(exc)
        assert result == "0xdeadbeef1234567890"

    def test_dict_arg_with_non_hex_data(self, mock_chain_interface, mock_abi_file):
        """Exception arg is dict with data key but not hex — skip it."""
        contract = MockContract(ADDR_A, "gnosis")
        exc = Exception({"data": "not-hex"})
        result = contract._extract_error_data(exc)
        assert result is None

    def test_dict_arg_without_data_key(self, mock_chain_interface, mock_abi_file):
        """Exception arg is dict but no data key — skip it."""
        contract = MockContract(ADDR_A, "gnosis")
        exc = Exception({"other": "value"})
        result = contract._extract_error_data(exc)
        assert result is None


# ---------------------------------------------------------------------------
# Line 214: _extract_error_data from exception.data attribute
# ---------------------------------------------------------------------------
class TestExtractErrorDataAttribute:
    def test_exception_data_attribute(self, mock_chain_interface, mock_abi_file):
        """Exception with .data attribute containing hex (lines 213-214)."""
        contract = MockContract(ADDR_A, "gnosis")
        exc = Exception("some message")
        exc.data = "0xabcdef0123456789"
        result = contract._extract_error_data(exc)
        assert result == "0xabcdef0123456789"

    def test_exception_data_attribute_non_hex(self, mock_chain_interface, mock_abi_file):
        """Exception with .data that is not hex — return None."""
        contract = MockContract(ADDR_A, "gnosis")
        exc = Exception("some message")
        exc.data = "not hex data"
        result = contract._extract_error_data(exc)
        assert result is None


# ---------------------------------------------------------------------------
# Lines 246-256: call() error handling with decoded errors
# ---------------------------------------------------------------------------
class TestCallErrorHandling:
    def test_call_with_decodable_error(self, mock_chain_interface, mock_abi_file):
        """call() extracts and decodes error, then re-raises (lines 246-256)."""
        contract = MockContract(ADDR_A, "gnosis")

        # Build a valid Error(string) error_data
        error_data = (
            "0x08c379a0"
            "0000000000000000000000000000000000000000000000000000000000000020"
            "0000000000000000000000000000000000000000000000000000000000000005"
            "4572726f72000000000000000000000000000000000000000000000000000000"
        )
        exc = ContractCustomError(error_data)

        # Make with_retry raise the exception directly
        mock_chain_interface.with_retry.side_effect = exc

        with patch("iwa.core.contracts.contract.logger") as mock_logger:
            with pytest.raises(ContractCustomError):
                contract.call("testFunc")
            mock_logger.error.assert_called_once()
            call_msg = mock_logger.error.call_args[0][0]
            assert "Error" in call_msg
            assert "testFunc" in call_msg

    def test_call_with_non_decodable_error(self, mock_chain_interface, mock_abi_file):
        """call() with error that has no extractable data — just re-raises (line 246-248)."""
        contract = MockContract(ADDR_A, "gnosis")
        exc = Exception("generic failure with no hex data")
        mock_chain_interface.with_retry.side_effect = exc

        with pytest.raises(Exception, match="generic failure"):
            contract.call("testFunc")

    def test_call_with_error_data_but_decode_returns_none(self, mock_chain_interface, mock_abi_file):
        """call() extracts error data but decode returns None — still re-raises (lines 248-250)."""
        contract = MockContract(ADDR_A, "gnosis")
        # Short hex data that passes extraction but not decoding
        exc = ContractCustomError("0x12345678")
        mock_chain_interface.with_retry.side_effect = exc

        with patch("iwa.core.contracts.contract.ErrorDecoder") as mock_decoder_cls:
            mock_decoder = mock_decoder_cls.return_value
            mock_decoder.decode.return_value = []
            with pytest.raises(ContractCustomError):
                contract.call("testFunc")


# ---------------------------------------------------------------------------
# Lines 266, 269-271: _sanitize_for_web3 (dict, list, tuple, str subclass)
# ---------------------------------------------------------------------------
class TestSanitizeForWeb3:
    def test_sanitize_str_subclass(self, mock_chain_interface, mock_abi_file):
        """EthereumAddress (str subclass) gets converted to pure str (line 266)."""
        contract = MockContract(ADDR_A, "gnosis")

        class StrSubclass(str):
            pass

        val = StrSubclass("hello")
        result = contract._sanitize_for_web3(val)
        assert result == "hello"
        assert type(result) is str

    def test_sanitize_dict(self, mock_chain_interface, mock_abi_file):
        """Dict values get recursively sanitized (line 268)."""
        contract = MockContract(ADDR_A, "gnosis")

        class StrSubclass(str):
            pass

        val = {"key": StrSubclass("addr"), "num": 42}
        result = contract._sanitize_for_web3(val)
        assert result == {"key": "addr", "num": 42}
        assert type(result["key"]) is str

    def test_sanitize_list(self, mock_chain_interface, mock_abi_file):
        """List values get recursively sanitized (lines 269-270)."""
        contract = MockContract(ADDR_A, "gnosis")

        class StrSubclass(str):
            pass

        val = [StrSubclass("a"), "b", 3]
        result = contract._sanitize_for_web3(val)
        assert result == ["a", "b", 3]
        assert type(result) is list
        assert type(result[0]) is str

    def test_sanitize_tuple(self, mock_chain_interface, mock_abi_file):
        """Tuple values get recursively sanitized preserving type (lines 269-270)."""
        contract = MockContract(ADDR_A, "gnosis")

        class StrSubclass(str):
            pass

        val = (StrSubclass("x"), 1)
        result = contract._sanitize_for_web3(val)
        assert result == ("x", 1)
        assert type(result) is tuple
        assert type(result[0]) is str

    def test_sanitize_plain_value(self, mock_chain_interface, mock_abi_file):
        """Plain int/str passes through unchanged (line 271)."""
        contract = MockContract(ADDR_A, "gnosis")
        assert contract._sanitize_for_web3(42) == 42
        assert contract._sanitize_for_web3("plain") == "plain"


# ---------------------------------------------------------------------------
# Line 332: extract_events with None receipt
# ---------------------------------------------------------------------------
class TestExtractEventsNoneReceipt:
    def test_extract_events_none_receipt(self, mock_chain_interface, mock_abi_file):
        """None receipt returns empty list (line 332)."""
        contract = MockContract(ADDR_A, "gnosis")
        events = contract.extract_events(None)
        assert events == []

    def test_extract_events_empty_receipt(self, mock_chain_interface, mock_abi_file):
        """Falsy receipt returns empty list (line 332)."""
        contract = MockContract(ADDR_A, "gnosis")
        events = contract.extract_events({})
        assert events == []


# ---------------------------------------------------------------------------
# Additional: ContractCustomError with non-str first arg
# ---------------------------------------------------------------------------
class TestExtractErrorContractCustomError:
    def test_contract_custom_error_non_str_arg(self, mock_chain_interface, mock_abi_file):
        """ContractCustomError with non-str first arg returns None (line 198)."""
        contract = MockContract(ADDR_A, "gnosis")
        exc = ContractCustomError(12345)
        result = contract._extract_error_data(exc)
        assert result is None
