"""Test that _get_or_create_agent_account funds on the correct chain.

Regression test for: agent funding TX was sent to Gnosis (default)
regardless of which chain the service was being deployed on, causing
nonce collisions during parallel multi-chain deploys.
"""

from unittest.mock import MagicMock

from web3 import Web3


class TestAgentFundingChain:
    """Verify wallet.send receives chain_name from the ServiceManager."""

    def _make_mock_manager(self, chain_name: str = "base"):
        """Create a mock with the attributes _get_or_create_agent_account needs."""
        mgr = MagicMock()
        mgr.chain_name = chain_name
        mgr.service.service_name = f"service_123"
        mgr.wallet.master_account.address = "0x" + "aa" * 20

        mock_account = MagicMock()
        mock_account.address = "0x" + "bb" * 20
        mgr.wallet.key_storage.generate_new_account.return_value = mock_account
        mgr.wallet.send.return_value = "0xtxhash"

        return mgr

    def test_fund_agent_uses_correct_chain(self):
        """wallet.send must receive chain_name=self.chain_name, not default."""
        from iwa.plugins.olas.service_manager.lifecycle import LifecycleManagerMixin

        mgr = self._make_mock_manager(chain_name="base")
        result = LifecycleManagerMixin._get_or_create_agent_account(mgr, None)

        assert result == "0x" + "bb" * 20
        mgr.wallet.send.assert_called_once()
        assert mgr.wallet.send.call_args.kwargs["chain_name"] == "base"

    def test_fund_agent_gnosis(self):
        """Gnosis chain passes chain_name='gnosis'."""
        from iwa.plugins.olas.service_manager.lifecycle import LifecycleManagerMixin

        mgr = self._make_mock_manager(chain_name="gnosis")
        LifecycleManagerMixin._get_or_create_agent_account(mgr, None)
        assert mgr.wallet.send.call_args.kwargs["chain_name"] == "gnosis"

    def test_fund_agent_arbitrary_chains(self):
        """Any chain_name is passed through, not hardcoded."""
        from iwa.plugins.olas.service_manager.lifecycle import LifecycleManagerMixin

        for chain in ["arbitrum", "polygon", "optimism", "celo", "ethereum"]:
            mgr = self._make_mock_manager(chain_name=chain)
            LifecycleManagerMixin._get_or_create_agent_account(mgr, None)
            assert mgr.wallet.send.call_args.kwargs["chain_name"] == chain

    def test_fund_amount_is_0_1_ether(self):
        """Funding amount is 0.1 native (not hardcoded xDAI amount)."""
        from iwa.plugins.olas.service_manager.lifecycle import LifecycleManagerMixin

        mgr = self._make_mock_manager(chain_name="base")
        LifecycleManagerMixin._get_or_create_agent_account(mgr, None)
        assert mgr.wallet.send.call_args.kwargs["amount_wei"] == Web3.to_wei(0.1, "ether")

    def test_existing_address_skips_creation(self):
        """If agent_address is provided, skip creation and funding."""
        from iwa.plugins.olas.service_manager.lifecycle import LifecycleManagerMixin

        mgr = self._make_mock_manager()
        result = LifecycleManagerMixin._get_or_create_agent_account(
            mgr, "0x" + "cc" * 20,
        )
        assert result == "0x" + "cc" * 20
        mgr.wallet.send.assert_not_called()
