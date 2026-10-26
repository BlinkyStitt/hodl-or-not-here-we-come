from dataclasses import replace
from decimal import Decimal

import pytest

from hodl import staking
from hodl.cache import Cache
from hodl.catalog import CRV, SDT, pools, strategies, verify
from hodl.config import rpc_url
from hodl.data import Archive, Prices
from hodl.fork import ACCOUNT, Fork
from hodl.model import Price
from hodl.simulation import Simulator


@pytest.mark.fork
@pytest.mark.parametrize("name", ["convex-cvxcrv-staked", "stakedao-sdcrv-onchain"])
def test_staking_restore_reproduces_claim_without_double_counting(tmp_path, name):
    url = rpc_url()
    if not url:
        pytest.skip("HODL_RPC_URL is required")
    cache = Cache(tmp_path / "staking.sqlite")
    archive = Archive(url, cache)
    archive.check_mainnet()
    block = archive.block(19_000_000)
    strategy = next(s for s in strategies() if s.name == name)
    verify(archive, strategy, block)
    amount = 1000 * 10**18
    with Fork(archive, block) as fork:
        fork.seed(strategy.underlying, amount)
        staking.deposit(fork, strategy, amount)
        state = staking.capture(fork, strategy)
        # A controlled one-hour clock advance tests the deployed accrual rules.
        # It is not a historical return estimate or a replacement for later state.
        fork.block = replace(block, timestamp=block.timestamp + 3600)
        expected = staking.claim(fork, strategy)
        assert any(expected.values())
        fork.set_mapping(strategy.address, "balanceOf(address)", (ACCOUNT,), 0)
        staking.restore(fork, strategy, amount, state)
        assert staking.claim(fork, strategy) == expected
        paid = staking.capture(fork, strategy)
        staking.restore(fork, strategy, amount, paid)
        assert not any(staking.claim(fork, strategy).values())
        staking.withdraw(fork, strategy, amount)
        assert fork.balance(strategy.underlying) == amount
        assert (
            fork.call(strategy.address, "balanceOf(address)", ("address",), (ACCOUNT,))
            == 0
        )
    cache.close()


@pytest.mark.fork
@pytest.mark.parametrize("name", ["convex-cvxcrv-staked", "stakedao-sdcrv-onchain"])
def test_historical_staking_claims_match_public_integral_changes(tmp_path, name):
    url = rpc_url()
    if not url:
        pytest.skip("HODL_RPC_URL is required")
    cache = Cache(tmp_path / "integrals.sqlite")
    archive = Archive(url, cache)
    archive.check_mainnet()
    strategy = next(s for s in strategies() if s.name == name)
    shares = 1000 * 10**18
    with Fork(archive, archive.block(19_000_000)) as fork:
        fork.seed(strategy.underlying, shares)
        staking.deposit(fork, strategy, shares)
        state = staking.capture(fork, strategy)
    with Fork(archive, archive.block(19_100_000)) as fork:
        staking.restore(fork, strategy, shares, state)
        if strategy.kind == "stakedao":
            assert (
                fork.call(
                    strategy.address,
                    "integrate_checkpoint_of(address)",
                    ("address",),
                    (ACCOUNT,),
                )
                == state.checkpoint
            )
            with fork.snapshot():
                normal_rewards = staking.claim(fork, strategy)
                normal_gas = fork.transactions[-1]["gas_units"]
            with fork.snapshot():
                fork.set_mapping(
                    strategy.address, "integrate_checkpoint_of(address)", (ACCOUNT,), 0
                )
                assert staking.claim(fork, strategy) == normal_rewards
                assert fork.transactions[-1]["gas_units"] - normal_gas == 17_100
        actual = staking.claim(fork, strategy)
        old = {r.token: r for r in state.rewards}
        for token, paid in actual.items():
            previous = old.get(token, staking.StakingReward(token, 0, 0))
            if strategy.kind == "convex":
                rewards = [
                    staking.wrapper_reward(fork, strategy.address, i)
                    for i in range(fork.call(strategy.address, "rewardLength()"))
                ]
                integral = next(r[2] for r in rewards if r[0].lower() == token.address)
                expected = (
                    previous.claim_data
                    + (shares // 2) * (integral - previous.integral) // 10**20
                )
            else:
                data = fork.call(
                    strategy.address,
                    "reward_data(address)",
                    ("address",),
                    (token.address,),
                    ("address", "address", "uint256", "uint256", "uint256", "uint256"),
                )
                balance = shares * 40 // 100 if token == SDT else shares
                expected = (previous.claim_data >> 128) + balance * (
                    data[-1] - previous.integral
                ) // 10**18
            assert paid == expected
        assert any(actual.values())
    cache.close()


class UnitPrices(Prices):
    def __init__(self):
        pass

    def at(self, token, timestamp):
        return Price(Decimal(1), timestamp, "test-only unit price")


@pytest.mark.fork
def test_staking_exit_keeps_rounding_dust_without_blocking_principal(tmp_path):
    url = rpc_url()
    if not url:
        pytest.skip("HODL_RPC_URL is required")
    cache = Cache(tmp_path / "dust.sqlite")
    archive = Archive(url, cache)
    archive.check_mainnet()
    start, end = (archive.block(n) for n in (20_207_948, 20_429_972))
    strategy = next(s for s in strategies() if s.name == "convex-cvxcrv-staked")
    verified = verify(archive, strategy, start)
    shares = 1000 * 10**18
    with Fork(archive, start) as fork:
        fork.seed(strategy.underlying, shares)
        staking.deposit(fork, strategy, shares)
        state = staking.capture(fork, strategy)
    with Fork(archive, end) as fork:
        staking.restore(fork, strategy, shares, state)
        rewards = staking.claim(fork, strategy)
    three_crv = pools()[0].lp
    assert 0 < rewards[three_crv] < 10**12
    result = Simulator(archive, UnitPrices()).exit(
        end, verified, CRV, shares, state, {}
    )
    assert result.amount > 0
    assert {(r.token, r.amount) for r in result.residuals} == {
        (three_crv, rewards[three_crv])
    }
    assert any(t["label"] == "unstake cvxCRV" for t in result.transactions)
    assert result.gas_units == sum(t["gas_units"] for t in result.transactions)
    cache.close()
