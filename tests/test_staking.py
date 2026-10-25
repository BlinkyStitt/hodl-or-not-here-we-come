from dataclasses import replace

import pytest

from hodl import staking
from hodl.cache import Cache
from hodl.catalog import SDT, strategies, verify
from hodl.config import rpc_url
from hodl.data import Archive
from hodl.fork import ACCOUNT, Fork


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
