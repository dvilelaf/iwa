"""Olas General Router."""

from fastapi import APIRouter, Depends
from loguru import logger

from iwa.web.dependencies import verify_auth

router = APIRouter(tags=["olas"])


@router.get(
    "/price",
    summary="Get OLAS Price",
    description="Get the current price of OLAS token in EUR from CoinGecko.",
)
def get_olas_price(auth: bool = Depends(verify_auth)):
    """Get current OLAS token price in EUR from CoinGecko."""
    try:
        from iwa.core.pricing import PriceService

        price_service = PriceService()
        price = price_service.get_token_price("autonolas", "eur")

        return {"price_eur": price, "symbol": "OLAS"}
    except Exception as e:
        logger.error(f"Error fetching OLAS price: {e}")
        return {"price_eur": None, "symbol": "OLAS", "error": str(e)}
