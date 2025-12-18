from unittest.mock import MagicMock, patch

from eth_account import Account

from iwa.core.chain import ChainInterface, SupportedChains

# --- Helpers ---
VALID_ADDR_1 = Account.create().address
VALID_ADDR_2 = Account.create().address


def test_chain_interface_coverage():
    # Patch RateLimitedWeb3 to bypass rate limiting wrapper
    with patch("iwa.core.chain.RateLimitedWeb3", side_effect=lambda w3, rl, ci: w3):
        interface = ChainInterface(SupportedChains().gnosis)
        interface.chain.rpcs = ["http://rpc1", "http://rpc2"]
        interface.web3 = MagicMock()
        interface.web3.provider.endpoint_uri = "http://rpc1"

        rotated = interface.rotate_rpc()
        assert rotated is True
        assert interface.web3.provider.endpoint_uri == "http://rpc2"

        interface.web3.eth.get_code = MagicMock(return_value=b"code")
        assert interface.is_contract(VALID_ADDR_1) is True

        interface.web3.eth.get_code.return_value = b""
        assert interface.is_contract(VALID_ADDR_2) is False

        with patch("iwa.core.contracts.erc20.ERC20Contract") as mock_erc20:
            instance = mock_erc20.return_value
            instance.symbol = "SYM"
            instance.decimals = 18

            interface.web3.eth.get_code.return_value = b"code"

            sym = interface.get_token_symbol(VALID_ADDR_1)
            assert sym == "SYM"

            dec = interface.get_token_decimals(VALID_ADDR_1)
            assert dec == 18
