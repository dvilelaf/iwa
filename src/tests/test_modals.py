"""Tests for TUI modals to boost coverage."""

import pytest
from textual.app import App, ComposeResult
from textual.containers import Container

# === Modal compose tests - these test the UI rendering paths ===


@pytest.mark.asyncio
async def test_create_eoa_modal_compose():
    """Cover CreateEOAModal.compose (lines 56-64)."""
    from iwa.tui.modals.base import CreateEOAModal

    modal = CreateEOAModal()

    class TestApp(App):
        def compose(self) -> ComposeResult:
            yield Container()

    app = TestApp()
    async with app.run_test() as pilot:
        app.push_screen(modal)
        await pilot.pause()

        # Verify modal is mounted
        assert modal.is_mounted


@pytest.mark.asyncio
async def test_create_safe_modal_compose():
    """Cover CreateSafeModal.compose (lines 128-149)."""
    from iwa.tui.modals.base import CreateSafeModal

    accounts = [("wallet1", "0x123"), ("wallet2", "0x456")]
    modal = CreateSafeModal(existing_accounts=accounts)

    class TestApp(App):
        def compose(self) -> ComposeResult:
            yield Container()

    app = TestApp()
    async with app.run_test() as pilot:
        app.push_screen(modal)
        await pilot.pause()

        assert modal.is_mounted


@pytest.mark.asyncio
async def test_stake_service_modal_compose():
    """Cover StakeServiceModal.compose (lines 205-214)."""
    from iwa.tui.modals.base import StakeServiceModal

    contracts = [("Contract1", "0xabc"), ("Contract2", "0xdef")]
    modal = StakeServiceModal(contracts=contracts)

    class TestApp(App):
        def compose(self) -> ComposeResult:
            yield Container()

    app = TestApp()
    async with app.run_test() as pilot:
        app.push_screen(modal)
        await pilot.pause()

        assert modal.is_mounted


@pytest.mark.asyncio
async def test_create_service_modal_compose():
    """Cover CreateServiceModal.compose (lines 280-303)."""
    from iwa.tui.modals.base import CreateServiceModal

    chains = ["gnosis", "ethereum"]
    staking_contracts = [("Staking1", "0xabc")]
    modal = CreateServiceModal(
        chains=chains, default_chain="gnosis", staking_contracts=staking_contracts
    )

    class TestApp(App):
        def compose(self) -> ComposeResult:
            yield Container()

    app = TestApp()
    async with app.run_test() as pilot:
        app.push_screen(modal)
        await pilot.pause()

        assert modal.is_mounted


@pytest.mark.asyncio
async def test_fund_service_modal_compose():
    """Cover FundServiceModal.compose (lines 371-382)."""
    from iwa.tui.modals.base import FundServiceModal

    modal = FundServiceModal(service_key="gnosis:1", native_symbol="xDAI")

    class TestApp(App):
        def compose(self) -> ComposeResult:
            yield Container()

    app = TestApp()
    async with app.run_test() as pilot:
        app.push_screen(modal)
        await pilot.pause()

        assert modal.is_mounted
