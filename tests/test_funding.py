from contextlib import contextmanager
from decimal import Decimal

import pytest

from hodl.catalog import USDC, WBTC, WETH, VerifiedStrategy, strategies
from hodl.data import Prices
from hodl.fork import Fork
from hodl.model import Block, DepositLimit, Price, Unaffordable
from hodl.routes import Router
from hodl.simulation import Simulator


class FundingFork(Fork):
    def __init__(self):
        self.block = Block(1, "test", 1)
        self.gas_units = 0
        self.transactions = []

    @contextmanager
    def snapshot(self):
        gas, count = self.gas_units, len(self.transactions)
        try:
            yield
        finally:
            self.gas_units = gas
            del self.transactions[count:]


class UnitPrice(Prices):
    def __init__(self):
        pass

    def at(self, token, timestamp):
        return Price(Decimal(1), timestamp, "test")


@pytest.mark.parametrize("token", [USDC, WBTC, WETH])
@pytest.mark.parametrize("capacity,expected", [(95, 90), (85, None)])
def test_gas_funded_deposit_checks_net_amount(monkeypatch, token, capacity, expected):
    fork = FundingFork()
    simulator = object.__new__(Simulator)
    simulator.prices = UnitPrice()
    router = Router(fork, simulator.prices)
    monkeypatch.setattr(simulator, "costs", lambda block, gas: (gas, Decimal(gas)))
    requested = []

    def deposit(fork, router, verified, source, amount):
        requested.append(amount)
        if amount > token.units(Decimal(capacity)):
            raise DepositLimit(amount, token.units(Decimal(capacity)))
        fork.gas_units += 10
        fork.transactions.append({"amount": amount, "gas_units": 10})
        return amount, ()

    monkeypatch.setattr("hodl.simulation.deposit", deposit)
    strategy = next(s for s in strategies() if s.name == "yearn-usdc-v2")
    verified = VerifiedStrategy(strategy, fork.block, None, None, "code")
    if expected is None:
        with pytest.raises(DepositLimit):
            simulator.funded_deposit(
                fork, router, verified, token, token.units(Decimal(100))
            )
    else:
        result = simulator.funded_deposit(
            fork, router, verified, token, token.units(Decimal(100))
        )
        assert result.amount == token.units(Decimal(expected))
        assert result.gas_usd == 10
        assert result.dust == 0
        assert result.transactions == ({"amount": result.amount, "gas_units": 10},)
    assert requested[0] == token.units(Decimal(100))
    assert requested[-1] == token.units(Decimal(90))
    assert fork.gas_units == 0
    assert fork.transactions == []


def test_probe_gas_can_exceed_the_budget(monkeypatch):
    fork = FundingFork()
    simulator = object.__new__(Simulator)
    simulator.prices = UnitPrice()
    router = Router(fork, simulator.prices)
    strategy = next(s for s in strategies() if s.name == "yearn-usdc-v2")
    verified = VerifiedStrategy(strategy, fork.block, None, None, "code")
    monkeypatch.setattr(simulator, "costs", lambda block, gas: (gas, Decimal(101)))
    monkeypatch.setattr("hodl.simulation.deposit", lambda *args: (1, ()))
    with pytest.raises(Unaffordable, match="cannot cover"):
        simulator.funded_deposit(fork, router, verified, USDC, 100 * 10**6)
