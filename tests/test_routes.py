from contextlib import contextmanager
from decimal import Decimal

import pytest

from hodl.catalog import ETH, STETH, USDC, USDT, WBTC, WETH, pools
from hodl.data import Archive, Prices
from hodl.fork import Fork
from hodl.model import Block, Price, Reverted, Unaffordable, Unavailable
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


class SwapFork(RouteFork):
    def __init__(self, partial_fee):
        super().__init__()
        self.partial_fee = partial_fee
        self.balances = {WBTC: 101, WETH: 7, USDC: 13}
        self.transactions = []

    def balance(self, token):
        return self.balances.get(token, 0)

    def approve(self, token, spender, amount):
        pass

    def call(self, *args, **kwargs):
        return 200

    def transact(self, address, signature, types=(), args: tuple = (), **kwargs):
        source, target, fee, _, _, amount, _, _ = args[0]
        tokens = {token.address: token for token in self.balances}
        spent = amount - 1 if fee == self.partial_fee else amount
        self.balances[tokens[source]] -= spent
        self.balances[tokens[target]] += 200
        self.gas_units += 1
        self.transactions.append({"label": kwargs["label"]})

    @contextmanager
    def snapshot(self):
        balances = self.balances.copy()
        transactions = self.transactions.copy()
        with super().snapshot():
            try:
                yield
            finally:
                self.balances = balances
                self.transactions = transactions


@pytest.mark.parametrize("partial_hop", [0, 1])
def test_partial_v3_fill_rejects_the_whole_route(monkeypatch, partial_hop):
    fork = SwapFork(partial_fee=(500, 3000)[partial_hop])
    router = Router(fork, DollarPrices())
    path = (Hop(WBTC, WETH, fee=500), Hop(WETH, USDC, fee=3000))
    monkeypatch.setattr(
        router,
        "hops",
        lambda source, target: tuple(
            hop for hop in path if (source, target) == (hop.source, hop.target)
        ),
    )
    with pytest.raises(Unavailable, match="partial Uniswap V3 fill"):
        router.convert(WBTC, USDC, 100)
    assert fork.balances == {WBTC: 101, WETH: 7, USDC: 13}
    assert fork.transactions == []
    assert fork.gas_units == 0


def test_partial_v3_candidate_does_not_hide_a_full_fill(monkeypatch):
    fork = SwapFork(partial_fee=500)
    router = Router(fork, DollarPrices())
    monkeypatch.setattr(
        router,
        "hops",
        lambda source, target: (
            (Hop(WBTC, USDC, fee=500), Hop(WBTC, USDC, fee=3000))
            if (source, target) == (WBTC, USDC)
            else ()
        ),
    )
    output, route = router.convert(WBTC, USDC, 100)
    assert output == 200
    assert fork.balances == {WBTC: 1, WETH: 7, USDC: 213}
    assert len(route) == 1
    assert "fee=3000" in route[0]


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


@pytest.mark.parametrize("pool", [None, pools()[0]])
def test_positive_reward_with_zero_quote_is_retained(monkeypatch, pool):
    fork = RouteFork()
    monkeypatch.setattr(fork, "balance", lambda token: 0)
    monkeypatch.setattr(fork, "call", lambda *args: 0)
    router = Router(fork, DollarPrices())
    hop = Hop(USDT, USDC, pool=pool, fee=3000)
    monkeypatch.setattr(
        router,
        "hops",
        lambda source, target: (hop,) if (source, target) == (USDT, USDC) else (),
    )
    with pytest.raises(Unaffordable, match="too small"):
        router.best(USDT, USDC, 1)
    assert fork.gas_units == 0


def test_absent_pool_remains_missing_data(monkeypatch):
    router = Router(RouteFork(), DollarPrices())
    monkeypatch.setattr(router, "hops", lambda *args: ())
    with pytest.raises(Unavailable, match="no deployed pool") as exc:
        router.best(USDT, USDC, 1)
    assert not isinstance(exc.value, Unaffordable)


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
