from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from hodl.catalog import CRV, CVXCRV, VerifiedStrategy, pools, strategies
from hodl.model import Block, Reverted, TokenBalance, Unaffordable, Unavailable
from hodl.routes import Router
from hodl.simulation import Execution, Simulator
from hodl.staking import StakingState


@pytest.mark.parametrize("error", [Unavailable("missing route"), Reverted("bad call")])
def test_missing_reward_route_is_not_treated_as_rounding_dust(error):
    router = MagicMock(spec=Router)
    router.convert.side_effect = error
    with pytest.raises(type(error), match=str(error)):
        Simulator.settle_rewards(router, CRV, {CVXCRV: 10**18})


def test_retained_reward_combines_with_later_claim_before_conversion(monkeypatch):
    three_crv = pools()[0].lp
    block = Block(1, "hash", 1)
    strategy = next(s for s in strategies() if s.name == "convex-cvxcrv-staked")
    verified = VerifiedStrategy(strategy, block, None, None, "code")
    state = StakingState(())
    simulator = object.__new__(Simulator)
    simulator.archive = MagicMock()
    simulator.prices = MagicMock()
    fork = MagicMock()
    fork.__enter__.return_value = fork
    balances = {}
    fork.balance.side_effect = lambda token: balances.get(token, 0)
    fork.seed.side_effect = lambda token, amount: balances.__setitem__(token, amount)
    monkeypatch.setattr("hodl.simulation.Fork", lambda *args: fork)
    monkeypatch.setattr("hodl.simulation.staking.restore", lambda *args: None)
    claims = iter(
        [{three_crv: 4 * 10**11, CRV: 10**18}, {three_crv: 8 * 10**11, CRV: 2 * 10**18}]
    )

    def claim(*args):
        rewards = next(claims)
        balances.clear()
        balances.update(rewards)
        return rewards

    monkeypatch.setattr("hodl.simulation.staking.claim", claim)
    router = MagicMock(spec=Router)
    conversions = []

    def convert(token, target, amount):
        conversions.append((token, amount))
        if token == three_crv and amount < 10**12:
            raise Unaffordable("LP redemption rounds to zero")
        balances[token] -= amount
        return amount, ("converted",)

    router.convert.side_effect = convert
    monkeypatch.setattr("hodl.simulation.Router", lambda *args: router)
    monkeypatch.setattr(
        simulator, "cached", lambda kind, block, request, fetch: fetch()
    )
    monkeypatch.setattr(
        simulator,
        "funded_deposit",
        lambda fork, router, verified, coin, proceeds, route: Execution(
            proceeds - 7, 3, 0, 0, Decimal(0), route, (), state
        ),
    )
    first = simulator.compound(block, verified, 100 * 10**18, state, {})
    assert first.amount == 10**18 - 7
    assert first.residuals == (TokenBalance(three_crv, 4 * 10**11),)
    assert balances[three_crv] == 4 * 10**11
    idle = {r.token: r.amount for r in first.residuals}
    idle[CVXCRV] = first.dust
    second = simulator.compound(block, verified, 101 * 10**18, state, idle)
    assert second.amount == 2 * 10**18 + 12 * 10**11 + 3 - 7
    assert second.residuals == ()
    assert balances[three_crv] == 0
    assert [amount for token, amount in conversions if token == three_crv] == [
        4 * 10**11,
        12 * 10**11,
    ]
