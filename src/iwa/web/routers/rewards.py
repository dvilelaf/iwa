"""Rewards Router for Web API — staking rewards tracking and tax reporting."""

import csv
import datetime
import io
from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from iwa.core.db import SentTransaction
from iwa.web.dependencies import verify_auth

router = APIRouter(prefix="/api/rewards", tags=["rewards"])

# Display precision constants for rounding
OLAS_DISPLAY_DECIMALS = 6  # OLAS token amounts
EUR_PRICE_DECIMALS = 4     # EUR price per OLAS
EUR_VALUE_DECIMALS = 2     # Total EUR value

GNOSIS_EXPLORER = "https://gnosisscan.io/tx/"


def _wei_to_olas(amount_wei: Optional[int]) -> float:
    """Convert wei amount to OLAS (1e18 decimals)."""
    return float(amount_wei or 0) / 1e18


def _query_claims(year: int, month: Optional[int] = None):
    """Query claim transactions for a given year (and optional month)."""
    year_start = datetime.datetime(year, 1, 1)
    year_end = datetime.datetime(year + 1, 1, 1)

    query = SentTransaction.tags.contains("olas_claim_rewards") & (
        SentTransaction.timestamp >= year_start
    ) & (SentTransaction.timestamp < year_end)

    if month and 1 <= month <= 12:
        month_start = datetime.datetime(year, month, 1)
        if month == 12:
            month_end = datetime.datetime(year + 1, 1, 1)
        else:
            month_end = datetime.datetime(year, month + 1, 1)
        query = query & (SentTransaction.timestamp >= month_start) & (
            SentTransaction.timestamp < month_end
        )

    return SentTransaction.select().where(query).order_by(SentTransaction.timestamp.asc())


def _validate_year_month(year: int, month: Optional[int] = None) -> int:
    """Validate and default year/month params. Returns resolved year."""
    if year == 0:
        year = datetime.datetime.now().year
    if year < 2020 or year > 2100:
        raise HTTPException(status_code=400, detail="Invalid year")
    if month is not None and (month < 1 or month > 12):
        raise HTTPException(status_code=400, detail="Invalid month (1-12)")
    return year


def _claim_to_dict(tx) -> dict:
    """Convert a SentTransaction to a claim dict."""
    olas_amount = _wei_to_olas(tx.amount_wei)
    return {
        "date": tx.timestamp.isoformat(),
        "tx_hash": tx.tx_hash,
        "olas_amount": round(olas_amount, OLAS_DISPLAY_DECIMALS),
        "price_eur": round(tx.price_eur, EUR_PRICE_DECIMALS) if tx.price_eur else None,
        "value_eur": round(tx.value_eur, EUR_VALUE_DECIMALS) if tx.value_eur else None,
        "service_name": tx.to_tag or tx.to_address,
        "chain": tx.chain,
        "explorer_url": f"{GNOSIS_EXPLORER}{tx.tx_hash}" if tx.chain == "gnosis" else None,
    }


@router.get(
    "/claims",
    summary="Get Claim Transactions",
    description="Retrieve staking reward claim transactions for a given year and optional month.",
)
def get_claims(
    year: int = 0,
    month: Optional[int] = None,
    auth: bool = Depends(verify_auth),
):
    """Get claim transactions for a year (and optional month)."""
    year = _validate_year_month(year, month)
    claims = _query_claims(year, month)
    return [_claim_to_dict(tx) for tx in claims]


@router.get(
    "/summary",
    summary="Get Rewards Summary",
    description="Get aggregated staking rewards summary by month for a given year.",
)
def get_summary(year: int = 0, auth: bool = Depends(verify_auth)):
    """Get rewards summary aggregated by month."""
    year = _validate_year_month(year)
    claims = _query_claims(year)

    total_olas = 0.0
    total_eur = 0.0
    total_claims = 0
    monthly = defaultdict(lambda: {"olas": 0.0, "eur": 0.0, "claims": 0})

    for tx in claims:
        olas_amount = _wei_to_olas(tx.amount_wei)
        eur_value = tx.value_eur or 0.0

        total_olas += olas_amount
        total_eur += eur_value
        total_claims += 1

        month = tx.timestamp.month
        monthly[month]["olas"] += olas_amount
        monthly[month]["eur"] += eur_value
        monthly[month]["claims"] += 1

    months = []
    for m in range(1, 13):
        data = monthly.get(m, {"olas": 0.0, "eur": 0.0, "claims": 0})
        months.append(
            {
                "month": m,
                "olas": round(data["olas"], OLAS_DISPLAY_DECIMALS),
                "eur": round(data["eur"], EUR_VALUE_DECIMALS),
                "claims": data["claims"],
            }
        )

    return {
        "year": year,
        "total_olas": round(total_olas, OLAS_DISPLAY_DECIMALS),
        "total_eur": round(total_eur, EUR_VALUE_DECIMALS),
        "total_claims": total_claims,
        "months": months,
    }


@router.get(
    "/by-trader",
    summary="Get Rewards Breakdown by Trader",
    description="Per-trader breakdown with monthly detail and cumulative totals.",
)
def get_by_trader(year: int = 0, auth: bool = Depends(verify_auth)):
    """Per-trader rewards breakdown with monthly detail."""
    year = _validate_year_month(year)
    claims = _query_claims(year)

    # Per-trader monthly data
    trader_data = defaultdict(lambda: {
        "total_olas": 0.0,
        "total_eur": 0.0,
        "total_claims": 0,
        "months": defaultdict(lambda: {"olas": 0.0, "eur": 0.0, "claims": 0}),
        "prices": [],
    })

    # Cumulative time series (all traders combined, by claim order)
    cumulative_series = []
    running_olas = 0.0
    running_eur = 0.0

    for tx in claims:
        olas_amount = _wei_to_olas(tx.amount_wei)
        eur_value = tx.value_eur or 0.0
        price = tx.price_eur
        trader = tx.to_tag or tx.to_address or "unknown"
        month = tx.timestamp.month

        td = trader_data[trader]
        td["total_olas"] += olas_amount
        td["total_eur"] += eur_value
        td["total_claims"] += 1
        td["months"][month]["olas"] += olas_amount
        td["months"][month]["eur"] += eur_value
        td["months"][month]["claims"] += 1
        if price is not None:
            td["prices"].append(price)

        running_olas += olas_amount
        running_eur += eur_value
        cumulative_series.append({
            "date": tx.timestamp.isoformat(),
            "olas": round(running_olas, OLAS_DISPLAY_DECIMALS),
            "eur": round(running_eur, EUR_VALUE_DECIMALS),
            "trader": trader,
        })

    # Build response
    traders = []
    for name, td in sorted(trader_data.items(), key=lambda x: -x[1]["total_eur"]):
        avg_price = sum(td["prices"]) / len(td["prices"]) if td["prices"] else None
        months = []
        for m in range(1, 13):
            md = td["months"].get(m, {"olas": 0.0, "eur": 0.0, "claims": 0})
            months.append({
                "month": m,
                "olas": round(md["olas"], OLAS_DISPLAY_DECIMALS),
                "eur": round(md["eur"], EUR_VALUE_DECIMALS),
                "claims": md["claims"],
            })
        traders.append({
            "name": name,
            "total_olas": round(td["total_olas"], OLAS_DISPLAY_DECIMALS),
            "total_eur": round(td["total_eur"], EUR_VALUE_DECIMALS),
            "total_claims": td["total_claims"],
            "avg_price_eur": round(avg_price, EUR_PRICE_DECIMALS) if avg_price else None,
            "months": months,
        })

    return {
        "year": year,
        "traders": traders,
        "cumulative": cumulative_series,
    }


@router.get(
    "/export",
    summary="Export Rewards CSV",
    description="Export staking rewards as a downloadable CSV file.",
)
def export_rewards(
    year: int = 0,
    month: Optional[int] = None,
    auth: bool = Depends(verify_auth),
):
    """Export claim transactions as CSV."""
    year = _validate_year_month(year, month)
    claims = _query_claims(year, month)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Date", "Service", "Tx Hash", "Explorer Link",
        "OLAS Amount", "EUR Price", "EUR Value",
    ])

    for tx in claims:
        olas_amount = _wei_to_olas(tx.amount_wei)
        explorer_url = f"{GNOSIS_EXPLORER}{tx.tx_hash}" if tx.chain == "gnosis" else ""
        writer.writerow([
            tx.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            tx.to_tag or tx.to_address or "",
            tx.tx_hash,
            explorer_url,
            f"{olas_amount:.{OLAS_DISPLAY_DECIMALS}f}",
            f"{tx.price_eur:.{EUR_PRICE_DECIMALS}f}" if tx.price_eur else "",
            f"{tx.value_eur:.{EUR_VALUE_DECIMALS}f}" if tx.value_eur else "",
        ])

    output.seek(0)
    suffix = f"_{month:02d}" if month else ""
    filename = f"olas_rewards_{year}{suffix}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
