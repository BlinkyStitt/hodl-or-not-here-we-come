"""Required release checks. Skips explicitly when no mainnet archive is configured."""

from dataclasses import replace
from decimal import Decimal

import pytest

from hodl.cache import Cache
from hodl.catalog import (
    CRV,
    CRVUSD,
    CVX,
    CVXCRV,
    ETH,
    SDCRV,
    SDT,
    USDC,
    YCRV,
    Strategy,
    pools,
    routing_pools,
    strategies,
    verify,
)
from hodl.config import rpc_url
from hodl.data import Archive, Prices
from hodl.fork import ACCOUNT, Fork
from hodl.model import Price, reward_accrual
from hodl.positions import (
    GaugeState,
    RewardState,
    checkpoint_integrals,
    claim,
    deposit,
    deposit_coin,
    gauge_state,
    seed_gauge,
    withdraw,
)
from hodl.routes import Hop, Router, mint_route


class UnitPrices(Prices):
    """No conversions occur in the contract tests; price is not a return estimate."""

    def __init__(self):
        pass

    def at(self, token, timestamp):
        return Price(Decimal(1), timestamp, "test-only unit price")


@pytest.fixture
def archive(tmp_path):
    url = rpc_url()
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
        return 24_400_000
    if any(
        part in name
        for part in ("crv-cvxcrv", "ycrv", "sdcrv", "convex-", "eth-steth-factory")
    ):
        return 19_000_000
    return 14_000_000


@pytest.mark.fork
@pytest.mark.parametrize("token", [YCRV, CVXCRV, SDCRV], ids=lambda t: t.symbol)
@pytest.mark.parametrize("number", [19_000_000, 20_000_000, 24_000_000])
def test_liquid_locker_mint_spends_crv_and_credits_tokens(archive, token, number):
    block = archive.block(number)
    amount = 1000 * 10**18
    with Fork(archive, block) as fork:
        fork.seed(CRV, amount)
        mint = mint_route(fork, token)
        assert mint is not None
        output = Router(fork, UnitPrices()).execute_hop(
            Hop(CRV, mint.token, mint=mint), amount
        )
        assert fork.balance(CRV) == 0
        assert output == fork.balance(mint.token)
        assert (
            output >= amount
        )  # Lock incentives can add tokens; no redemption implied.


@pytest.mark.fork
@pytest.mark.parametrize("pool", routing_pools()[len(pools()) :], ids=lambda p: p.name)
def test_reward_route_pool_identity(archive, pool):
    block = archive.block(19_000_000)
    verify(
        archive,
        Strategy(pool.name, pool.address, "lp", pool.version, pool.lp, pool),
        block,
    )


@pytest.mark.fork
@pytest.mark.parametrize("source,target", [(CVX, CVXCRV), (SDT, SDCRV)])
def test_reward_conversion_can_use_three_steps(archive, source, target):
    block = archive.block(19_000_000)
    amount = 100 * 10**18
    with Fork(archive, block) as fork:
        fork.seed(source, amount)
        output, route = Router(fork, UnitPrices()).convert(source, target, amount)
        assert fork.balance(source) == 0
        assert output == fork.balance(target) > 0
        assert route


def unclaimed_state(strategy, block, integrals):
    """Define an unclaimed position independently of the state-capture code."""
    assert strategy.pool is not None
    return GaugeState(
        integrals.crv,
        0,
        0,
        block.timestamp,
        tuple(
            RewardState(
                token,
                integral,
                0 if strategy.pool.gauge_version in ("v3", "factory") else None,
            )
            for token, integral in integrals.extra
        ),
    )


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
    assert verified.gauge is not None
    shares = 10**18
    with Fork(archive, start) as fork:
        before = checkpoint_integrals(fork, verified)
    state = unclaimed_state(strategy, start, before)
    with Fork(archive, end) as fork:
        after = checkpoint_integrals(fork, verified)
    with Fork(archive, end) as fork:
        seed_gauge(fork, verified, shares, state)
        actual = claim(fork, verified)
    assert actual[CRV] == reward_accrual(shares, before.crv, after.crv, crv=True)
    old = {token.address.lower(): value for token, value in before.extra}
    for token, value in after.extra:
        assert actual[token] == reward_accrual(
            shares, old.get(token.address.lower(), 0), value, crv=False
        )


@pytest.mark.fork
@pytest.mark.parametrize(
    "strategy", [s for s in strategies() if s.kind == "gauge"], ids=lambda s: s.name
)
def test_repeated_gauge_claims_restore_state_and_receipt_gas(archive, strategy):
    numbers = (
        (18_994_253, 19_215_377, 19_422_438)
        if fixed_block(strategy.name) >= 19_000_000
        else (13_916_165, 14_116_761, 14_297_758)
    )
    start, first, second = (archive.block(number) for number in numbers)
    verified = verify(archive, strategy, start)
    assert verified.gauge is not None
    shares = 10**18
    with Fork(archive, start) as fork:
        before = checkpoint_integrals(fork, verified)
    initial = unclaimed_state(strategy, start, before)
    with Fork(archive, first) as fork:
        seed_gauge(fork, verified, shares, initial)
        claim(fork, verified)
        prior = gauge_state(fork, verified)
    assert prior.fraction == prior.minted > 0
    assert prior.checkpoint == first.timestamp

    # A hypothetical exit at the same boundary must not claim those rewards again.
    with Fork(archive, first) as fork:
        seed_gauge(fork, verified, shares, prior)
        assert gauge_state(fork, verified) == prior
        assert all(amount == 0 for amount in claim(fork, verified).values())

    with Fork(archive, second) as fork:
        seed_gauge(fork, verified, shares, prior)
        assert gauge_state(fork, verified) == prior
        rewards = claim(fork, verified)
        repeated_gas = fork.transactions[0]["gas_units"]
        after = gauge_state(fork, verified)
    assert after.fraction == after.minted > prior.minted

    # Reproduce the old first-write error while holding all other state fixed.
    with Fork(archive, second) as fork:
        seed_gauge(fork, verified, shares, replace(prior, fraction=0, minted=0))
        assert claim(fork, verified) == rewards
        first_write_gas = fork.transactions[0]["gas_units"]
    assert first_write_gas - repeated_gas == 34_200

    # Preserve both halves of packed extra-reward accounting, including pending
    # rewards. V2 gauges pay at checkpoints and do not have this packed field.
    packed = tuple(
        replace(reward, claim_data=reward.claim_data + (17 << 128))
        if reward.claim_data is not None
        else reward
        for reward in prior.extra
    )
    if packed != prior.extra:
        pending = replace(prior, extra=packed)
        with Fork(archive, second) as fork:
            seed_gauge(fork, verified, shares, pending)
            assert gauge_state(fork, verified) == pending
            actual = claim(fork, verified)
        expected = rewards.copy()
        for reward in packed:
            if reward.claim_data is not None:
                expected[reward.token] += 17
        assert actual == expected
    print(
        f"{strategy.name}: repeated CRV claim gas={repeated_gas}, "
        f"reset-counter gas={first_write_gas}, rewards={rewards}"
    )


@pytest.mark.fork
@pytest.mark.parametrize("target", [CRV, CVXCRV, SDCRV], ids=lambda t: t.symbol)
@pytest.mark.parametrize("number", [21_089_068, 26_230_066])
def test_crvusd_reward_conversion_at_staking_boundary(archive, target, number):
    source = CRVUSD
    # Actual sdCRV reward amount at the November 2024 comparison boundary.
    amount = 48_482_534_210_147_964_407
    block = archive.block(number)
    with Fork(archive, block) as fork:
        fork.seed(source, amount)
        output, route = Router(fork, UnitPrices()).convert(source, target, amount)
        assert fork.balance(source) == 0
        assert output == fork.balance(target) > 0
        assert route
