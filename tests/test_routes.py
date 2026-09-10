from contextlib import contextmanager
from decimal import Decimal

import pytest

from hodl.catalog import ETH, STETH, USDC, WBTC, WETH
from hodl.data import Archive, Prices
from hodl.fork import Fork
from hodl.model import Block, Price, Reverted, Unavailable
from hodl.routes import Hop, Router


class FixedGas(Archive):
    def __init__(self):
        pass

    def gas_price(self, block):
        return 10**18


class RouteFork(Fork):
    def __init__(self):
        self.block = Block(14_000_000, "block", 1640995200)
        self.archive = FixedGas()
        self.gas_units = 0
        self.wraps = []

    def wrap(self, amount):
        self.wraps.append(("wrap", amount))

    def unwrap(self, amount):
        self.wraps.append(("unwrap", amount))

    @contextmanager
    def snapshot(self):
        gas = self.gas_units
        try:
            yield
        finally:
            self.gas_units = gas


class DollarPrices(Prices):
    def __init__(self):
        pass

    def at(self, token, timestamp):
        return Price(Decimal(1), timestamp, "test")


class CandidateRouter(Router):
    def __init__(self, *, error=None):
        super().__init__(RouteFork(), DollarPrices())
        self.error = error
        self.paths = []

    def hops(self, source, target):
        edges = {(WBTC, USDC), (WBTC, WETH), (WETH, USDC)}
        return (Hop(source, target, fee=3000),) if (source, target) in edges else ()

    def execute(self, source, target, amount, hops):
        self.paths.append(hops)
        if len(hops) == 2:
            if self.error:
                raise self.error
            self.fork.gas_units += 20
            return 110 * 10**6
        self.fork.gas_units += 5
        return 100 * 10**6


def test_route_selection_compares_net_value_after_gas():
    router = CandidateRouter()
    best = router.best(WBTC, USDC, 10**8)
    # Two swaps return more tokens but cost $20; direct costs only $5.
    assert best.output == 100 * 10**6
    assert best.net_usd == Decimal(95)
    assert best.gas_units == 5
    assert len(best.hops) == 1
    assert {len(path) for path in router.paths} == {1, 2}
    assert router.fork.gas_units == 0


def test_reverted_route_does_not_hide_other_supported_routes():
    best = CandidateRouter(error=Reverted("pool has no liquidity")).best(
        WBTC, USDC, 10**8
    )
    assert best.output == 100 * 10**6


def test_missing_route_data_is_not_silently_omitted():
    with pytest.raises(Unavailable, match="archive transport"):
        CandidateRouter(error=Unavailable("archive transport failed")).best(
            WBTC, USDC, 10**8
        )


@pytest.mark.parametrize(
    "source,target,hop,expected",
    [
        (ETH, STETH, Hop(ETH, STETH), []),
        (STETH, ETH, Hop(STETH, ETH), []),
        (ETH, USDC, Hop(WETH, USDC), [("wrap", 100)]),
        (USDC, ETH, Hop(USDC, WETH), [("unwrap", 200)]),
    ],
)
def test_wrap_only_when_the_route_requires_it(
    monkeypatch, source, target, hop, expected
):
    fork = RouteFork()
    router = Router(fork, DollarPrices())
    monkeypatch.setattr(router, "execute_hop", lambda hop, amount: 2 * amount)
    assert router.execute(source, target, 100, (hop,)) == 200
    assert fork.wraps == expected
