from decimal import Decimal

import pytest

from hodl.model import Block, Observation
from hodl.report import comparison_records, table


def observation(strategy, amount, *, asset="ETH", target=100, status="complete"):
    return Observation(
        strategy,
        asset,
        target,
        Block(target, str(target), target),
        status,
        start_quantity=Decimal(2),
        end_quantity=Decimal(amount) if amount is not None else None,
    )


def test_token_benchmarks_use_matching_dates_assets_and_complete_outcomes():
    rows = [
        observation("hold-ETH", "2"),
        observation("yearn-weth-v2", "2.1"),
        observation("yearn-usdc-v2", "2.15"),
        observation("yearn-eth-steth-v2", "2.2"),
        observation("curve-eth-steth-gauge", "3", status="incomplete"),
        observation("yearn-usdc-v2", "100000", asset="USD"),
        observation("yearn-eth-steth-v2", "9", target=200),
    ]
    records = comparison_records(rows)
    vault = records[1]
    assert vault["token_return_fraction"] == Decimal("0.05")
    assert vault["best_strategy"] == "yearn-eth-steth-v2"
    assert vault["versus_best_quantity"] == Decimal("-0.1")
    assert vault["single_vault_strategy"] == "yearn-weth-v2"
    assert vault["versus_single_vault_quantity"] == 0
    assert records[3]["versus_single_vault_quantity"] == Decimal("0.1")
    assert records[3]["versus_best_quantity"] == 0
    assert records[4]["versus_best_quantity"] is None
    assert records[4]["token_return_fraction"] is None
    assert records[6]["versus_best_quantity"] == 0
    rendered = table(rows[:5])
    assert "Best selected option: yearn-eth-steth-v2" in rendered
    assert "Single-asset vault: yearn-weth-v2" in rendered
    assert "vs best quantity" in rendered
    assert "vs vault quantity" in rendered


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
    assert row["versus_single_vault_quantity"] is None


def test_all_unavailable_results_have_no_winner():
    row = comparison_records(
        [observation("yearn-weth-v2", None, status="unavailable-exit")]
    )[0]
    assert row["best_strategy"] is None
    assert row["versus_best_quantity"] is None
