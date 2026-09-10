from decimal import Decimal

import pytest

from hodl.model import Block, Observation
from hodl.report import comparison_records, table


def observation(strategy, amount, *, asset="ETH", target=100, status="complete"):
    initial_price = Decimal(5000) if asset == "ETH" else Decimal(1)
    quantity = Decimal(amount) if amount is not None else None
    return Observation(
        strategy,
        asset,
        target,
        Block(target, str(target), target),
        status,
        start_quantity=Decimal(10000) / initial_price,
        end_quantity=quantity,
        end_usd=quantity * initial_price if quantity is not None else None,
    )


def test_best_uses_all_assets_at_same_date_and_plain_vault_matches_starting_asset():
    rows = [
        observation("hold-ETH", "2"),
        observation("yearn-weth-v2", "2.1"),
        observation("yearn-usdc-v2", "2.15"),
        observation("yearn-eth-steth-v2", "2.2"),
        observation("curve-eth-steth-gauge", "3", status="incomplete"),
        observation("yearn-usdc-v2", "12000", asset="USD"),
        observation("yearn-eth-steth-v2", "9", target=200),
    ]
    records = comparison_records(rows)
    vault = records[1]
    assert vault["token_return_fraction"] == Decimal("0.05")
    assert vault["best_strategy"] == "yearn-usdc-v2"
    assert vault["best_asset"] == "USD"
    assert vault["versus_best_usd"] == Decimal("-1500")
    assert vault["single_vault_strategy"] == "yearn-weth-v2"
    assert vault["versus_single_vault_usd"] == 0
    assert records[3]["versus_single_vault_usd"] == Decimal("500")
    assert records[3]["versus_best_usd"] == Decimal("-1000")
    assert records[4]["versus_best_usd"] is None
    assert records[4]["token_return_fraction"] is None
    assert records[5]["versus_best_usd"] == 0
    assert records[6]["best_strategy"] == "yearn-eth-steth-v2"
    assert records[6]["best_asset"] == "ETH"
    assert records[6]["versus_best_usd"] == 0
    rendered = table(rows)
    assert rendered.startswith(
        "ETH: gaps use net USD proceeds. Best across the comparison: yearn-usdc-v2/USD."
    )
    assert "Single-asset vault: yearn-weth-v2" in rendered
    assert "vs best USD" in rendered
    assert "vs vault USD" in rendered


def test_best_compares_usd_value_instead_of_token_units():
    records = comparison_records(
        [
            observation("yearn-usdc-v2", "10001", asset="USD"),
            observation("yearn-eth-steth-v2", "2.2"),
        ]
    )
    assert records[0]["best_strategy"] == "yearn-eth-steth-v2"
    assert records[0]["best_asset"] == "ETH"
    assert records[0]["versus_best_usd"] == Decimal("-999")


@pytest.mark.parametrize("strategy,asset", [("hold-CRV", "CRV"), ("cash-USD", "cash")])
def test_holding_and_cash_are_eligible_global_winners(strategy, asset):
    records = comparison_records(
        [
            observation("yearn-eth-steth-v2", "1.8"),
            observation(strategy, "10000", asset=asset),
        ]
    )
    assert records[0]["best_strategy"] == strategy
    assert records[0]["best_asset"] == asset
    assert records[0]["versus_best_usd"] == Decimal("-1000")


@pytest.mark.parametrize(
    "rows,status",
    [
        ([observation("curve-eth-steth-lp", "2.1")], "not selected"),
        (
            [
                observation("curve-eth-steth-lp", "2.1"),
                observation("yearn-weth-v2", None, status="unavailable-entry"),
            ],
            "unavailable",
        ),
        ([observation("yearn-crv-cvxcrv-v2", "2.1", asset="CRV")], "not in catalog"),
    ],
)
def test_missing_plain_asset_vault_is_explicit(rows, status):
    row = comparison_records(rows)[0]
    assert row["single_vault_status"] == status
    assert row["single_vault_strategy"] is None
    assert row["versus_single_vault_usd"] is None


def test_all_unavailable_results_have_no_winner():
    row = comparison_records(
        [observation("yearn-weth-v2", None, status="unavailable-exit")]
    )[0]
    assert row["best_strategy"] is None
    assert row["best_asset"] is None
    assert row["versus_best_usd"] is None
