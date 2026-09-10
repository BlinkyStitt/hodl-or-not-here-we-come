"""Required release checks. Skips explicitly when no mainnet archive is configured."""

import os
from decimal import Decimal

import pytest

from hodl.cache import Cache
from hodl.catalog import CRV, ETH, USDC, strategies, verify
from hodl.data import Archive, Prices
from hodl.fork import ACCOUNT, Fork
from hodl.model import Price, reward_accrual
from hodl.positions import (
    checkpoint_integrals,
    claim,
    deposit,
    deposit_coin,
    seed_gauge,
    withdraw,
)
from hodl.routes import Router


class UnitPrices(Prices):
    """No conversions occur in the contract tests; price is not a return estimate."""

    def __init__(self):
        pass

    def at(self, token, timestamp):
        return Price(Decimal(1), timestamp, "test-only unit price")


@pytest.fixture
def archive(tmp_path):
    url = os.environ.get("HODL_RPC_URL")
    if not url:
        pytest.skip("HODL_RPC_URL is required for fixed-block mainnet verification")
    cache = Cache(tmp_path / "mainnet.sqlite")
    result = Archive(url, cache)
    result.finalized()  # Prove mainnet before reading historical blocks.
    try:
        yield result
    finally:
        cache.close()


def fixed_block(name: str) -> int:
    if name == "yearn-usd-v3":
        return 24_000_000
    if "crv-cvxcrv" in name:
        return 19_000_000
    return 14_000_000


@pytest.mark.fork
@pytest.mark.parametrize("strategy", strategies(), ids=lambda s: s.name)
def test_contract_deposit_redemption_and_receipt_gas(archive, strategy):
    block = archive.block(fixed_block(strategy.name))
    verified = verify(archive, strategy, block)
    assert archive.code(verified.deployment, strategy.address) != "0x"
    if verified.deployment.number:
        assert (
            archive.code(
                archive.block(verified.deployment.number - 1), strategy.address
            )
            == "0x"
        )
    coin = deposit_coin(strategy, USDC)
    quantity = {"ETH": Decimal(1), "WETH": Decimal(1), "WBTC": Decimal("0.01")}.get(
        coin.symbol, Decimal(1000)
    )
    amount = coin.units(quantity)
    with Fork(archive, block) as fork:
        fork.seed(coin, amount)
        router = Router(fork, UnitPrices())
        before_eth = fork.balance(ETH)
        shares, entry_route = deposit(fork, router, verified, coin, amount)
        assert entry_route == ()
        assert shares > 0
        returned, exit_route = withdraw(fork, router, verified, coin, shares)
        assert exit_route == ()
        # A same-block round trip cannot create more deposit assets.
        assert 0 < returned <= amount
        assert fork.gas_units == sum(tx["gas_units"] for tx in fork.transactions)
        measured_eth_spend = before_eth - fork.balance(ETH)
        protocol_spend = amount - returned if coin == ETH else 0
        assert (
            measured_eth_spend - protocol_spend
            == fork.gas_units * archive.gas_price(block)
        )
        if verified.gauge:
            assert (
                fork.call(
                    verified.gauge, "balanceOf(address)", ("address",), (ACCOUNT,)
                )
                == 0
            )


@pytest.mark.fork
@pytest.mark.parametrize(
    "strategy", [s for s in strategies() if s.kind == "gauge"], ids=lambda s: s.name
)
def test_integrals_independently_match_real_gauge_claims(archive, strategy):
    start = archive.block(fixed_block(strategy.name))
    end = archive.block(start.number + 10_000)
    verified = verify(archive, strategy, start)
    with Fork(archive, start) as fork:
        before = checkpoint_integrals(fork, verified)
    with Fork(archive, end) as fork:
        after = checkpoint_integrals(fork, verified)
    shares = 10**18
    with Fork(archive, end) as fork:
        seed_gauge(fork, verified, shares, before)
        actual = claim(fork, verified)
    assert actual[CRV] == reward_accrual(shares, before.crv, after.crv, crv=True)
    old = {token.address.lower(): value for token, value in before.extra}
    for token, value in after.extra:
        assert actual[token] == reward_accrual(
            shares, old.get(token.address.lower(), 0), value, crv=False
        )
