"""Deployed liquid-locker staking rewards; no off-chain voting distributions."""

from dataclasses import dataclass

from eth_abi import encode
from web3 import Web3

from hodl.catalog import ZERO, Strategy
from hodl.data import calldata
from hodl.fork import ACCOUNT, Fork
from hodl.model import Token, Unavailable
from hodl.positions import token_at


@dataclass(frozen=True)
class StakingReward:
    token: Token
    integral: int
    claim_data: int


@dataclass(frozen=True)
class StakingState:
    rewards: tuple[StakingReward, ...]
    checkpoint: int | None = None


def reward_tokens(fork: Fork, strategy: Strategy) -> tuple[Token, ...]:
    address = strategy.address
    if strategy.kind == "convex":
        return tuple(
            token_at(fork, reward[0])
            for i in range(fork.call(address, "rewardLength()"))
            if (reward := wrapper_reward(fork, address, i))[0].lower() != ZERO
        )
    return tuple(
        token_at(
            fork,
            fork.call(
                address, "reward_tokens(uint256)", ("uint256",), (i,), ("address",)
            ),
        )
        for i in range(fork.call(address, "reward_count()"))
    )


def wrapper_reward(fork: Fork, address: str, index: int) -> tuple:
    return fork.call(
        address,
        "rewards(uint256)",
        ("uint256",),
        (index,),
        ("address", "uint8", "uint128", "uint128"),
    )


def wrapper_slots(fork: Fork, address: str, index: int) -> tuple[int, int]:
    """Prove the public struct's packed words before locating its account maps.

    CvxCrvStakingWrapper.RewardType has address+uint8, uint128+uint128,
    reward_integral_for, and claimable_reward, in four consecutive words.
    Source: convex-eth/platform contracts/contracts/wrappers/CvxCrvStakingWrapper.sol.
    Fork tests compare restored claims with uninterrupted deployed execution.
    """
    token, group, integral, remaining = wrapper_reward(fork, address, index)
    trace = fork.rpc(
        "debug_traceCall",
        [
            {
                "to": address,
                "data": calldata("rewards(uint256)", ("uint256",), (index,)),
            },
            "latest",
            {"disableMemory": True, "disableStorage": True},
        ],
    )
    expected = int(token, 16) | group << 160
    candidates = set(
        int(s["stack"][-1], 16) for s in trace["structLogs"] if s["op"] == "SLOAD"
    )
    bases = [
        slot
        for slot in candidates
        if int(fork.rpc("eth_getStorageAt", [address, hex(slot), "latest"]), 16)
        == expected
        and int(fork.rpc("eth_getStorageAt", [address, hex(slot + 1), "latest"]), 16)
        == integral | remaining << 128
    ]
    if len(bases) != 1:
        raise Unavailable("unverified Convex reward struct storage layout")
    slots = tuple(
        int.from_bytes(
            Web3.keccak(encode(("address", "uint256"), (ACCOUNT, bases[0] + offset))),
            "big",
        )
        for offset in (2, 3)
    )
    return slots[0], slots[1]


def capture(fork: Fork, strategy: Strategy) -> StakingState:
    address = strategy.address
    records = []
    for index, token in enumerate(reward_tokens(fork, strategy)):
        if strategy.kind == "convex":
            # Resolve by token, since invalidated slots remain in the array.
            index = next(
                i
                for i in range(fork.call(address, "rewardLength()"))
                if wrapper_reward(fork, address, i)[0].lower() == token.address.lower()
            )
            slots = wrapper_slots(fork, address, index)
            integral, claim_data = (
                int(fork.rpc("eth_getStorageAt", [address, hex(s), "latest"]), 16)
                for s in slots
            )
        else:
            integral = fork.call(
                address,
                "reward_integral_for(address,address)",
                ("address", "address"),
                (token.address, ACCOUNT),
            )
            claim_data = fork.mapping_word(
                address, "claimed_reward(address,address)", (ACCOUNT, token.address)
            )
        records.append(StakingReward(token, integral, claim_data))
    checkpoint = (
        fork.call(address, "integrate_checkpoint_of(address)", ("address",), (ACCOUNT,))
        if strategy.kind == "stakedao"
        else None
    )
    return StakingState(tuple(records), checkpoint)


def restore(fork: Fork, strategy: Strategy, shares: int, state: StakingState) -> None:
    address = strategy.address
    current = reward_tokens(fork, strategy)
    if {r.token for r in state.rewards} - set(current):
        raise Unavailable("staking reward token removed during the holding period")
    fork.set_mapping(address, "balanceOf(address)", (ACCOUNT,), shares)
    if strategy.kind == "convex":
        fork.set_mapping(address, "userRewardWeight(address)", (ACCOUNT,), 5000)
    else:
        fork.set_mapping(
            address, "working_balances(address)", (ACCOUNT,), shares * 40 // 100
        )
        if state.checkpoint is None:
            raise Unavailable("missing Stake DAO reward checkpoint")
        fork.set_mapping(
            address, "integrate_checkpoint_of(address)", (ACCOUNT,), state.checkpoint
        )
    for reward in state.rewards:
        if strategy.kind == "convex":
            index = next(
                i
                for i in range(fork.call(address, "rewardLength()"))
                if wrapper_reward(fork, address, i)[0].lower()
                == reward.token.address.lower()
            )
            for slot, value in zip(
                wrapper_slots(fork, address, index),
                (reward.integral, reward.claim_data),
                strict=True,
            ):
                fork.rpc(
                    "anvil_setStorageAt",
                    [address, hex(slot), "0x" + value.to_bytes(32, "big").hex()],
                )
        else:
            fork.set_mapping(
                address,
                "reward_integral_for(address,address)",
                (reward.token.address, ACCOUNT),
                reward.integral,
            )
            fork.set_mapping(
                address,
                "claimed_reward(address,address)",
                (ACCOUNT, reward.token.address),
                reward.claim_data,
                mask=2**128 - 1,
            )


def claim(fork: Fork, strategy: Strategy) -> dict[Token, int]:
    tokens = reward_tokens(fork, strategy)
    before = {t: fork.balance(t) for t in tokens}
    if strategy.kind == "convex":
        fork.transact(
            strategy.address,
            "getReward(address)",
            ("address",),
            (ACCOUNT,),
            label="claim Convex rewards",
        )
    else:
        fork.transact(
            strategy.address,
            "claim_rewards()",
            label="claim Stake DAO on-chain rewards",
        )
    return {t: fork.balance(t) - before[t] for t in tokens}


def deposit(fork: Fork, strategy: Strategy, amount: int) -> None:
    fork.approve(strategy.underlying, strategy.address, amount)
    if strategy.kind == "convex":
        if (
            fork.call(
                strategy.address, "userRewardWeight(address)", ("address",), (ACCOUNT,)
            )
            != 5000
        ):
            fork.transact(
                strategy.address,
                "stakeAndSetWeight(uint256,uint256)",
                ("uint256", "uint256"),
                (amount, 5000),
                label="stake cvxCRV with equal reward weights",
            )
        else:
            fork.transact(
                strategy.address,
                "stake(uint256,address)",
                ("uint256", "address"),
                (amount, ACCOUNT),
                label="stake cvxCRV",
            )
    else:
        fork.transact(
            strategy.address,
            "deposit(uint256)",
            ("uint256",),
            (amount,),
            label="stake sdCRV",
        )


def withdraw(fork: Fork, strategy: Strategy, shares: int) -> None:
    if strategy.kind == "convex":
        fork.transact(
            strategy.address,
            "withdraw(uint256)",
            ("uint256",),
            (shares,),
            label="unstake cvxCRV",
        )
    else:
        fork.transact(
            strategy.address,
            "withdraw(uint256)",
            ("uint256",),
            (shares,),
            label="unstake sdCRV",
        )
