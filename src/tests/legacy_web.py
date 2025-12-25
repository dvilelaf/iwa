"""Tests for the Web Server module."""

import pytest


class TestObscureUrl:
    """Tests for URL obscuring utility."""

    def test_obscure_url_hides_path(self):
        """Test that _obscure_url hides the path and query."""
        from iwa.web.server import _obscure_url

        result = _obscure_url("https://rpc.example.com/v1/api-key-12345")
        assert result == "https://rpc.example.com/..."
        assert "api-key" not in result

    def test_obscure_url_handles_empty(self):
        """Test that _obscure_url handles empty URLs."""
        from iwa.web.server import _obscure_url

        result = _obscure_url("")
        # Empty URL gives minimal output
        assert "..." in result

    def test_obscure_url_preserves_scheme_and_host(self):
        """Test that scheme and host are preserved."""
        from iwa.web.server import _obscure_url

        result = _obscure_url("wss://ws.alchemy.com/v2/secret")
        assert result == "wss://ws.alchemy.com/..."

    def test_obscure_url_handles_no_path(self):
        """Test URL with no path."""
        from iwa.web.server import _obscure_url

        result = _obscure_url("https://example.com")
        assert result == "https://example.com/..."


class TestInputValidation:
    """Tests for Pydantic input validation models."""

    def test_transaction_request_valid(self):
        """Test valid transaction request passes validation."""
        from iwa.web.server import TransactionRequest

        req = TransactionRequest(
            from_address="0x1234567890abcdef1234567890abcdef12345678",
            to_address="0xabcdef1234567890abcdef1234567890abcdef12",
            amount_eth=1.0,
            token="native",
            chain="gnosis",
        )
        assert req.from_address == "0x1234567890abcdef1234567890abcdef12345678"
        assert req.amount_eth == 1.0

    def test_transaction_request_valid_with_tag(self):
        """Test valid transaction request with tag passes validation."""
        from iwa.web.server import TransactionRequest

        req = TransactionRequest(
            from_address="my_wallet",
            to_address="receiver_wallet",
            amount_eth=1.0,
            token="native",
            chain="gnosis",
        )
        assert req.from_address == "my_wallet"

    def test_transaction_request_invalid_address_xss(self):
        """Test that XSS in address is rejected."""
        from pydantic import ValidationError

        from iwa.web.server import TransactionRequest

        with pytest.raises(ValidationError) as exc:
            TransactionRequest(
                from_address="<script>alert(1)</script>",
                to_address="0x1234567890abcdef1234567890abcdef12345678",
                amount_eth=1.0,
                token="native",
                chain="gnosis",
            )
        assert "alphanumeric" in str(exc.value).lower()

    def test_transaction_request_invalid_address_format(self):
        """Test that invalid hex address is rejected."""
        from pydantic import ValidationError

        from iwa.web.server import TransactionRequest

        with pytest.raises(ValidationError) as exc:
            TransactionRequest(
                from_address="0xINVALIDHEXADDRESS",
                to_address="0x1234567890abcdef1234567890abcdef12345678",
                amount_eth=1.0,
                token="native",
                chain="gnosis",
            )
        assert "invalid" in str(exc.value).lower()

    def test_transaction_request_empty_address(self):
        """Test that empty address is rejected."""
        from pydantic import ValidationError

        from iwa.web.server import TransactionRequest

        with pytest.raises(ValidationError):
            TransactionRequest(
                from_address="",
                to_address="0x1234567890abcdef1234567890abcdef12345678",
                amount_eth=1.0,
                token="native",
                chain="gnosis",
            )

    def test_transaction_request_negative_amount(self):
        """Test that negative amounts are rejected."""
        from pydantic import ValidationError

        from iwa.web.server import TransactionRequest

        with pytest.raises(ValidationError) as exc:
            TransactionRequest(
                from_address="0x1234567890abcdef1234567890abcdef12345678",
                to_address="0xabcdef1234567890abcdef1234567890abcdef12",
                amount_eth=-1.0,
                token="native",
                chain="gnosis",
            )
        assert "positive" in str(exc.value).lower()

    def test_transaction_request_zero_amount(self):
        """Test that zero amount is rejected."""
        from pydantic import ValidationError

        from iwa.web.server import TransactionRequest

        with pytest.raises(ValidationError):
            TransactionRequest(
                from_address="0x1234567890abcdef1234567890abcdef12345678",
                to_address="0xabcdef1234567890abcdef1234567890abcdef12",
                amount_eth=0,
                token="native",
                chain="gnosis",
            )

    def test_transaction_request_excessive_amount(self):
        """Test that excessive amount is rejected."""
        from pydantic import ValidationError

        from iwa.web.server import TransactionRequest

        with pytest.raises(ValidationError) as exc:
            TransactionRequest(
                from_address="0x1234567890abcdef1234567890abcdef12345678",
                to_address="0xabcdef1234567890abcdef1234567890abcdef12",
                amount_eth=1e20,
                token="native",
                chain="gnosis",
            )
        assert "large" in str(exc.value).lower()

    def test_transaction_request_xss_chain(self):
        """Test that XSS in chain field is rejected."""
        from pydantic import ValidationError

        from iwa.web.server import TransactionRequest

        with pytest.raises(ValidationError):
            TransactionRequest(
                from_address="0x1234567890abcdef1234567890abcdef12345678",
                to_address="0xabcdef1234567890abcdef1234567890abcdef12",
                amount_eth=1.0,
                token="native",
                chain="<script>",
            )

    def test_account_create_request_valid_tag(self):
        """Test valid tag passes validation."""
        from iwa.web.server import AccountCreateRequest

        req = AccountCreateRequest(tag="my_wallet_123")
        assert req.tag == "my_wallet_123"

    def test_account_create_request_none_tag(self):
        """Test None tag is allowed."""
        from iwa.web.server import AccountCreateRequest

        req = AccountCreateRequest(tag=None)
        assert req.tag is None

    def test_account_create_request_empty_tag(self):
        """Test empty tag becomes None."""
        from iwa.web.server import AccountCreateRequest

        req = AccountCreateRequest(tag="  ")
        assert req.tag is None

    def test_account_create_request_xss_tag(self):
        """Test that XSS in tag is rejected."""
        from pydantic import ValidationError

        from iwa.web.server import AccountCreateRequest

        with pytest.raises(ValidationError) as exc:
            AccountCreateRequest(tag="<script>alert(1)</script>")
        assert "alphanumeric" in str(exc.value).lower()

    def test_account_create_request_long_tag(self):
        """Test that too-long tags are rejected."""
        from pydantic import ValidationError

        from iwa.web.server import AccountCreateRequest

        with pytest.raises(ValidationError) as exc:
            AccountCreateRequest(tag="a" * 51)
        assert "long" in str(exc.value).lower()

    def test_account_create_request_with_underscore_hyphen(self):
        """Test that underscores and hyphens are allowed in tags."""
        from iwa.web.server import AccountCreateRequest

        req = AccountCreateRequest(tag="my-wallet_name")
        assert req.tag == "my-wallet_name"


class TestAppConfiguration:
    """Tests for app configuration."""

    def test_cors_middleware_configured(self):
        """Test that CORS middleware is configured."""
        from iwa.web.server import app

        # Check that user_middleware list is not empty (CORS was added)
        assert len(app.user_middleware) > 0

    def test_static_files_mounted(self):
        """Test that static files are mounted."""
        from iwa.web.server import app

        routes = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/static" in routes
