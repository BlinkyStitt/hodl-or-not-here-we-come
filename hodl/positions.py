"""Execute each deployed contract's deposit, claim, and redemption rules."""

from dataclasses import dataclass

from hodl.catalog import (
    CRV,
    ETH,
    MINTER,
    USDC,
    USDT,
    WETH,
    ZERO,
    Pool,
    Strategy,
    VerifiedStrategy,
)
from hodl.fork import ACCOUNT, Fork
from hodl.model import (
    DepositLimit,
    Token,
    Unavailable,
    v2_deposit_shares,
    v2_free_funds,
    v2_share_value,
)
from hodl.routes import Router


def token_at(fork: Fork, address: str) -> Token:
    return Token(
        fork.call(address, "symbol()", returns=("string",)),
        address,
        fork.call(address, "decimals()"),
    )


def share_token(strategy: Strategy) -> Token:
    if strategy.kind in ("lp", "gauge"):
        return strategy.underlying
    return Token(strategy.name, strategy.address, strategy.underlying.decimals)


def deposit_coin(strategy: Strategy, source: Token) -> Token:
    if strategy.pool is None:
        return strategy.underlying
    if source in strategy.pool.coins:
        return source
    if source == ETH and WETH in strategy.pool.coins:
        return WETH
    for preferred in (USDC, USDT, ETH, CRV):
        if preferred in strategy.pool.coins:
            return preferred
    raise Unavailable("pool has no supported entry coin")


def free_funds(fork: Fork, strategy: Strategy, *, deposit: bool = False) -> int:
    total = fork.call(strategy.address, "totalAssets()")
    # 0.3.0 has no locked-profit mechanism for either issuance or redemption.
    if strategy.version == "0.3.0":
        return total
    # 0.3.5 issues shares against totalAssets, but redeems against unlocked funds.
    if strategy.version == "0.3.5" and deposit:
        return total
    getter = (
        "lockedProfitDegration()"
        if strategy.version == "0.3.5"
        else "lockedProfitDegradation()"
    )
    return v2_free_funds(
        total,
        fork.call(strategy.address, "lockedProfit()"),
        fork.call(strategy.address, "lastReport()"),
        fork.call(strategy.address, getter),
        fork.block.timestamp,
    )


def pool_deposit(fork: Fork, pool: Pool, coin: Token, amount: int) -> int:
    before = fork.balance(pool.lp)
    amounts = [0] * len(pool.coins)
    amounts[pool.coins.index(coin)] = amount
    fork.approve(coin, pool.address, amount)
    array = f"uint256[{len(pool.coins)}]"
    fork.transact(
        pool.address,
        f"add_liquidity({array},uint256)",
        (array, "uint256"),
        (amounts, 0),
        value=amount if coin == ETH else 0,
        label=f"deposit {pool.name}",
    )
    shares = fork.balance(pool.lp) - before
    if shares <= 0:
        raise Unavailable("pool deposit minted no LP tokens")
    return shares


def pool_withdraw(fork: Fork, pool: Pool, coin: Token, shares: int) -> int:
    before = fork.balance(coin)
    gas_before = fork.gas_units
    fork.transact(
        pool.address,
        f"remove_liquidity_one_coin(uint256,{pool.index_type},uint256)",
        ("uint256", pool.index_type, "uint256"),
        (shares, pool.coins.index(coin), 0),
        label=f"withdraw {pool.name}",
    )
    output = fork.balance(coin) - before
    if coin == ETH:
        output += (fork.gas_units - gas_before) * fork.archive.gas_price(fork.block)
    if output <= 0:
        raise Unavailable("LP withdrawal produced no assets")
    return output


def deposit(
    fork: Fork,
    router: Router,
    verified: VerifiedStrategy,
    source: Token,
    amount: int,
) -> tuple[int, tuple[str, ...]]:
    strategy = verified.strategy
    coin = deposit_coin(strategy, source)
    underlying, route = router.convert(source, coin, amount)
    if strategy.pool:
        underlying = pool_deposit(fork, strategy.pool, coin, underlying)
    if strategy.kind in ("v2", "v3"):
        before = fork.balance(share_token(strategy))
        if strategy.kind == "v2":
            if fork.call(strategy.address, "emergencyShutdown()", returns=("bool",)):
                raise Unavailable("Yearn deposits are disabled by emergency shutdown")
            capacity = fork.call(strategy.address, "depositLimit()") - fork.call(
                strategy.address, "totalAssets()"
            )
            if underlying > capacity:
                raise DepositLimit(underlying, capacity)
            expected = v2_deposit_shares(
                underlying,
                fork.call(strategy.address, "totalSupply()"),
                free_funds(fork, strategy, deposit=True),
            )
        else:
            limit = fork.call(
                strategy.address, "maxDeposit(address)", ("address",), (ACCOUNT,)
            )
            if underlying > limit:
                raise DepositLimit(underlying, limit)
            expected = fork.call(
                strategy.address, "previewDeposit(uint256)", ("uint256",), (underlying,)
            )
        fork.approve(strategy.underlying, strategy.address, underlying)
        fork.transact(
            strategy.address,
            "deposit(uint256,address)",
            ("uint256", "address"),
            (underlying, ACCOUNT),
            label="Yearn deposit",
        )
        shares = fork.balance(share_token(strategy)) - before
        if shares != expected or shares == 0:
            raise Unavailable(
                f"deposit shares differ from accounting: "
                f"actual={shares}, expected={expected}"
            )
        return shares, route
    if verified.gauge:
        fork.approve(strategy.underlying, verified.gauge, underlying)
        fork.transact(
            verified.gauge,
            "deposit(uint256)",
            ("uint256",),
            (underlying,),
            label="stake LP",
        )
    return underlying, route


def withdraw(
    fork: Fork,
    router: Router,
    verified: VerifiedStrategy,
    target: Token,
    shares: int,
) -> tuple[int, tuple[str, ...]]:
    strategy = verified.strategy
    underlying = shares
    if verified.gauge:
        fork.transact(
            verified.gauge,
            "withdraw(uint256)",
            ("uint256",),
            (shares,),
            label="unstake LP",
        )
    if strategy.kind in ("v2", "v3"):
        before = fork.balance(strategy.underlying)
        if strategy.kind == "v3":
            assets = fork.call(
                strategy.address, "previewRedeem(uint256)", ("uint256",), (shares,)
            )
            # maxRedeem rounds assets back to shares and can understate a full
            # redeem by one share. Compare assets with the same loss policy.
            limit = fork.call(
                strategy.address,
                "maxWithdraw(address,uint256)",
                ("address", "uint256"),
                (ACCOUNT, 10000),
            )
            if assets > limit:
                raise Unavailable("Yearn redemption exceeds maxWithdraw")
            fork.transact(
                strategy.address,
                "redeem(uint256,address,address)",
                ("uint256", "address", "address"),
                (shares, ACCOUNT, ACCOUNT),
                label="Yearn redeem",
            )
        else:
            if shares > fork.call(strategy.address, "maxAvailableShares()"):
                raise Unavailable("Yearn shares exceed maxAvailableShares")
            fork.transact(
                strategy.address,
                "withdraw(uint256,address,uint256)",
                ("uint256", "address", "uint256"),
                (shares, ACCOUNT, 1),
                label="Yearn withdraw",
            )
        if fork.balance(share_token(strategy)):
            raise Unavailable("Yearn withdrawal left shares; full exit is blocked")
        underlying = fork.balance(strategy.underlying) - before
    coin = deposit_coin(strategy, target)
    if strategy.pool:
        underlying = pool_withdraw(fork, strategy.pool, coin, underlying)
    return router.convert(coin, target, underlying)


def accounting_assets(fork: Fork, strategy: Strategy, shares: int) -> int:
    if strategy.kind == "v2":
        return v2_share_value(
            shares,
            fork.call(strategy.address, "totalSupply()"),
            free_funds(fork, strategy),
        )
    if strategy.kind == "v3":
        return fork.call(
            strategy.address, "convertToAssets(uint256)", ("uint256",), (shares,)
        )
    return shares


@dataclass(frozen=True)
class Integrals:
    crv: int
    extra: tuple[tuple[Token, int], ...]
    killed: bool | None


@dataclass(frozen=True)
class RewardState:
    token: Token
    integral: int
    # V3/factory gauges pack accrued and previously claimed rewards in one word.
    # V2 gauges transfer rewards at each checkpoint and have no claim_data field.
    claim_data: int | None


@dataclass(frozen=True)
class GaugeState:
    integral: int
    fraction: int
    minted: int
    checkpoint: int
    extra: tuple[RewardState, ...]


def reward_tokens(fork: Fork, verified: VerifiedStrategy) -> tuple[Token, ...]:
    if not verified.gauge or not verified.strategy.pool:
        return ()
    if verified.strategy.pool.gauge_version == "original":
        return ()
    tokens = []
    for index in range(8):
        address = fork.call(
            verified.gauge,
            "reward_tokens(uint256)",
            ("uint256",),
            (index,),
            ("address",),
        )
        if address.lower() == ZERO:
            break
        tokens.append(token_at(fork, address))
    return tuple(tokens)


def checkpoint_integrals(fork: Fork, verified: VerifiedStrategy) -> Integrals:
    if not verified.gauge or not verified.strategy.pool:
        raise ValueError("not a gauge position")
    gauge = verified.gauge
    fork.transact(
        gauge,
        "user_checkpoint(address)",
        ("address",),
        (ACCOUNT,),
        label="boundary checkpoint",
    )
    period = fork.call(gauge, "period()", returns=("int128",))
    integral = fork.call(
        gauge, "integrate_inv_supply(uint256)", ("uint256",), (period,)
    )
    tokens = reward_tokens(fork, verified)
    if tokens:
        # Empty owner: update global integrals without claiming somebody else's reward.
        fork.transact(
            gauge,
            "claim_rewards()",
            label="boundary reward checkpoint",
        )
    extra = []
    for token in tokens:
        if verified.strategy.pool.gauge_version in ("v2", "v3"):
            value = fork.call(
                gauge, "reward_integral(address)", ("address",), (token.address,)
            )
        else:
            data = fork.call(
                gauge,
                "reward_data(address)",
                ("address",),
                (token.address,),
                ("address", "address", "uint256", "uint256", "uint256", "uint256"),
            )
            value = data[-1]
        extra.append((token, value))
    killed = (
        None
        if verified.strategy.pool.gauge_version == "original"
        else fork.call(gauge, "is_killed()", returns=("bool",))
    )
    return Integrals(integral, tuple(extra), killed)


def gauge_state(fork: Fork, verified: VerifiedStrategy) -> GaugeState:
    """Capture account state after a real simulated deposit or compound."""
    gauge = verified.gauge
    pool = verified.strategy.pool
    if not gauge or not pool:
        raise ValueError("not a gauge position")
    extra = tuple(
        RewardState(
            token,
            fork.call(
                gauge,
                "reward_integral_for(address,address)",
                ("address", "address"),
                (token.address, ACCOUNT),
            ),
            fork.mapping_word(
                gauge, "claimed_reward(address,address)", (ACCOUNT, token.address)
            )
            if pool.gauge_version in ("v3", "factory")
            else None,
        )
        for token in reward_tokens(fork, verified)
    )
    return GaugeState(
        fork.call(gauge, "integrate_inv_supply_of(address)", ("address",), (ACCOUNT,)),
        fork.call(gauge, "integrate_fraction(address)", ("address",), (ACCOUNT,)),
        fork.call(
            MINTER, "minted(address,address)", ("address", "address"), (ACCOUNT, gauge)
        ),
        fork.call(gauge, "integrate_checkpoint_of(address)", ("address",), (ACCOUNT,)),
        extra,
    )


def seed_gauge(
    fork: Fork, verified: VerifiedStrategy, shares: int, state: GaugeState
) -> None:
    if not verified.gauge:
        raise ValueError("missing gauge")
    gauge = verified.gauge
    current_tokens = reward_tokens(fork, verified)
    removed = {reward.token.address for reward in state.extra} - {
        t.address.lower() for t in current_tokens
    }
    if removed:
        raise Unavailable(
            "unsupported removed reward tokens: " + ", ".join(sorted(removed))
        )
    fork.set_mapping(gauge, "balanceOf(address)", (ACCOUNT,), shares)
    fork.set_mapping(gauge, "working_balances(address)", (ACCOUNT,), shares * 40 // 100)
    fork.set_mapping(
        gauge, "integrate_inv_supply_of(address)", (ACCOUNT,), state.integral
    )
    fork.set_mapping(gauge, "integrate_fraction(address)", (ACCOUNT,), state.fraction)
    fork.set_mapping(MINTER, "minted(address,address)", (ACCOUNT, gauge), state.minted)
    fork.set_mapping(
        gauge, "integrate_checkpoint_of(address)", (ACCOUNT,), state.checkpoint
    )
    for reward in state.extra:
        fork.set_mapping(
            gauge,
            "reward_integral_for(address,address)",
            (reward.token.address, ACCOUNT),
            reward.integral,
        )
        if reward.claim_data is not None:
            fork.set_mapping(
                gauge,
                "claimed_reward(address,address)",
                (ACCOUNT, reward.token.address),
                reward.claim_data,
                mask=2**128 - 1,
            )


def claim(fork: Fork, verified: VerifiedStrategy) -> dict[Token, int]:
    if not verified.gauge:
        return {}
    tokens = (CRV, *reward_tokens(fork, verified))
    before = {token: fork.balance(token) for token in tokens}
    fork.transact(
        MINTER, "mint(address)", ("address",), (verified.gauge,), label="claim CRV"
    )
    if len(tokens) > 1:
        fork.transact(
            verified.gauge,
            "claim_rewards()",
            label="claim extra rewards",
        )
    return {token: fork.balance(token) - before[token] for token in tokens}
