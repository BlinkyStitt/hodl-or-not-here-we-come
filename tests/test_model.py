from decimal import Decimal

import pytest

from hodl.catalog import CRV, ETH, USDC, WBTC, assets, strategies
from hodl.model import (
    Scenario,
    Token,
    Unavailable,
    anniversaries,
    parse_date,
    reward_accrual,
    v2_deposit_shares,
    v2_free_funds,
    v2_share_value,
)


def test_reward_token_identity_uses_address_and_decimals():
    reported = Token("USD Coin", USDC.address.upper(), 6)
    assert reported == USDC
    assert {USDC: 123}[reported] == 123
    assert reported.price_id == USDC.price_id
    assert Token("ETH", USDC.address, 6).price_id == USDC.price_id
    assert Token("native", ETH.address, 18).price_id == "coingecko:ethereum"
    assert Token("USDC", USDC.address, 18) != USDC


@pytest.mark.parametrize("token", [USDC, WBTC, CRV])
def test_yearn_regression_120_to_150_returns_125_percent(token):
    deposit = 12000 * 10**token.decimals
    supply = 10000 * 10**token.decimals
    shares = v2_deposit_shares(deposit, supply, 12000 * 10**token.decimals)
    result = v2_share_value(shares, supply, 15000 * 10**token.decimals)
    assert shares == 10000 * 10**token.decimals
    assert result == 15000 * 10**token.decimals
    # The original price-difference formula incorrectly returned 15,600.
    assert result != deposit + deposit * 30 // 100


@pytest.mark.parametrize("token", [USDC, WBTC, CRV])
def test_integer_amounts_round_only_at_token_boundaries(token):
    assert token.units(Decimal("1.0000000000000000009")) == 10**token.decimals
    assert (
        token.units(Decimal("1.0000000000000000009"), round_up=True)
        == 10**token.decimals + 1
    )
    assert token.quantity(1) == Decimal(1) / 10**token.decimals
    assert v2_deposit_shares(7, 10, 12) == 5
    assert v2_share_value(5, 10, 15) == 7


def test_vault_losses_and_zero_supply():
    assert v2_deposit_shares(25, 0, 0) == 25
    assert v2_share_value(10, 100, 50) == 5
    with pytest.raises(Unavailable, match="no free funds"):
        v2_deposit_shares(1, 10, 0)
    with pytest.raises(Unavailable, match="no outstanding"):
        v2_share_value(1, 0, 0)


def test_locked_profit_degrades_at_block_timestamp():
    assert v2_free_funds(1000, 100, 50, 10**16, 50) == 900
    assert v2_free_funds(1000, 100, 50, 10**16, 100) == 950
    assert v2_free_funds(1000, 100, 50, 10**16, 150) == 1000
    with pytest.raises(Unavailable, match="after"):
        v2_free_funds(1000, 100, 50, 10**16, 49)


def test_anniversaries_keep_original_day_and_final_partial_month():
    assert anniversaries(parse_date("2024-01-31"), parse_date("2024-04-12")) == tuple(
        map(
            parse_date,
            ("2024-02-29", "2024-03-31", "2024-04-12"),
        )
    )
    assert anniversaries(parse_date("2023-01-31"), parse_date("2023-03-31")) == tuple(
        map(
            parse_date,
            ("2023-02-28", "2023-03-31"),
        )
    )


def test_dates_require_explicit_timezone_for_timestamps():
    assert parse_date("2022-01-01") == parse_date("2022-01-01T00:00:00Z")
    assert parse_date("2021-12-31T16:00:00-08:00") == parse_date("2022-01-01")
    with pytest.raises(ValueError, match="timezone"):
        parse_date("2022-01-01T12:00:00")


@pytest.mark.parametrize(
    "value", [Decimal("NaN"), Decimal("Infinity"), Decimal(0), Decimal(-1)]
)
def test_reject_invalid_initial_value(value):
    with pytest.raises(ValueError):
        Scenario(1, 2, usd_value=value)


def test_rewards_use_integrals_not_current_rate_and_apply_unboosted_crv():
    # Two historical intervals with different rates, including a killed interval.
    shares = 101
    assert reward_accrual(shares, 2 * 10**18, 5 * 10**18, crv=True) == 120
    assert reward_accrual(shares, 5 * 10**18, 6 * 10**18, crv=True) == 40
    assert reward_accrual(shares, 6 * 10**18, 6 * 10**18, crv=True) == 0
    assert reward_accrual(shares, 2 * 10**18, 5 * 10**18, crv=False) == 303
    with pytest.raises(Unavailable, match="decreased"):
        reward_accrual(shares, 2, 1, crv=True)


def test_catalog_contains_all_fixed_positions_and_actual_wrapped_assets():
    catalog = strategies()
    assert len(catalog) == 15
    assert len({s.name for s in catalog}) == 15
    assert sum(s.kind == "gauge" for s in catalog) == 4
    assert all(s.gauge is None for s in catalog if s.kind != "gauge")
    assert assets()["USD"] == USDC
    assert assets()["BTC"] == WBTC
    assert next(s for s in catalog if s.name == "yearn-wbtc-v2").version == "0.3.5"


@pytest.mark.parametrize("deposit", [False, True])
def test_yearn_030_uses_total_assets_without_locked_profit(monkeypatch, deposit):
    from hodl.fork import Fork
    from hodl.positions import free_funds

    strategy = next(s for s in strategies() if s.name == "yearn-eth-steth-v2")
    fork = object.__new__(Fork)

    def call(address, signature):
        assert address == strategy.address
        # Version 0.3.0 does not have the later locked-profit getters.
        assert signature == "totalAssets()"
        return 1200

    monkeypatch.setattr(fork, "call", call)
    assert free_funds(fork, strategy, deposit=deposit) == 1200
