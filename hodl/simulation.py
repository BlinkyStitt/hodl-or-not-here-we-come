"""Historical action execution, gas funding, and cached fork evidence."""

import hashlib
import shutil
import subprocess
from dataclasses import asdict, dataclass
from decimal import Decimal, getcontext
from importlib.metadata import version
from pathlib import Path

from hodl.catalog import CRV, ETH, VerifiedStrategy
from hodl.data import Archive, Prices
from hodl.fork import Fork
from hodl.model import Block, DepositLimit, Reverted, Token, Unaffordable, Unavailable
from hodl.positions import (
    Integrals,
    accounting_assets,
    checkpoint_integrals,
    claim,
    deposit,
    deposit_coin,
    seed_gauge,
    share_token,
    withdraw,
)
from hodl.routes import Router


@dataclass(frozen=True)
class Execution:
    amount: int
    dust: int
    gas_units: int
    gas_wei: int
    gas_usd: Decimal
    route: tuple[str, ...]
    transactions: tuple[dict, ...]


class Simulator:
    def __init__(self, archive: Archive, prices: Prices):
        self.archive = archive
        self.prices = prices
        binary = shutil.which("anvil")
        anvil_version = (
            subprocess.check_output([binary, "--version"], text=True).strip()
            if binary
            else "not installed"
        )
        digest = hashlib.sha256()
        # These modules determine cached action results. CLI configuration and
        # report rendering do not; resolved inputs already form part of each key.
        for name in (
            "cache",
            "catalog",
            "data",
            "fork",
            "model",
            "positions",
            "routes",
            "simulation",
        ):
            path = Path(__file__).parent / f"{name}.py"
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
        self.engine = {
            "source_sha256": digest.hexdigest(),
            "decimal_precision": getcontext().prec,
            "decimal_rounding": getcontext().rounding,
            "anvil": anvil_version,
            "web3": version("web3"),
            "eth-abi": version("eth-abi"),
        }

    def evidence(self, kind: str, block: Block, request, fetch):
        def calculate():
            try:
                return {"value": fetch()}
            except Unavailable as exc:
                return {"error": str(exc), "error_type": type(exc).__name__}

        outcome = self.archive.cache.get(
            kind,
            [self.engine, request],
            self.archive.source,
            calculate,
            block_hash=block.hash,
        )
        if "error" in outcome:
            error_type = {"Unaffordable": Unaffordable, "Reverted": Reverted}.get(
                outcome["error_type"], Unavailable
            )
            raise error_type(outcome["error"])
        return outcome["value"]

    def costs(self, block: Block, gas_units: int) -> tuple[int, Decimal]:
        wei = gas_units * self.archive.gas_price(block)
        return wei, ETH.quantity(wei) * self.prices.at(ETH, block.timestamp).usd

    def execution(
        self, fork: Fork, amount: int, dust: int, route: tuple[str, ...]
    ) -> Execution:
        wei, usd = self.costs(fork.block, fork.gas_units)
        return Execution(
            amount, dust, fork.gas_units, wei, usd, route, tuple(fork.transactions)
        )

    def cached(self, kind: str, block: Block, request: dict, fetch) -> Execution:
        def calculate() -> dict:
            result = asdict(fetch())
            result["gas_usd"] = str(result["gas_usd"])
            return result

        raw = self.evidence("execution-v1", block, [kind, request], calculate)
        return Execution(
            raw["amount"],
            raw["dust"],
            raw["gas_units"],
            raw["gas_wei"],
            Decimal(raw["gas_usd"]),
            tuple(raw["route"]),
            tuple(raw["transactions"]),
        )

    def integrals(self, block: Block, verified: VerifiedStrategy) -> Integrals:
        def calculate() -> dict:
            with Fork(self.archive, block) as fork:
                return asdict(checkpoint_integrals(fork, verified))

        raw = self.evidence("integrals-v1", block, asdict(verified), calculate)
        return Integrals(
            raw["crv"],
            tuple((Token(**t), value) for t, value in raw["extra"]),
            raw["killed"],
        )

    def funded_deposit(
        self,
        fork: Fork,
        router: Router,
        verified: VerifiedStrategy,
        source: Token,
        budget: int,
        prefix: tuple[str, ...] = (),
    ) -> Execution:
        price = self.prices.at(source, fork.block.timestamp).usd
        reserve: int | None = None
        candidate = budget
        for _ in range(budget.bit_length() + 8):
            if candidate <= 0:
                raise Unaffordable("proceeds cannot cover the deposit and gas")
            with fork.snapshot():
                try:
                    amount, route = deposit(fork, router, verified, source, candidate)
                except DepositLimit as exc:
                    if reserve is not None or exc.capacity == 0:
                        raise
                    # Measure a permitted deposit before sizing the gas-funded entry.
                    # The snapshot discards this probe and all of its transactions.
                    candidate //= 2
                    continue
                gas_wei, gas_usd = self.costs(fork.block, fork.gas_units)
                debit = source.units(gas_usd / price, round_up=True)
                if reserve is not None and debit <= reserve:
                    return Execution(
                        amount,
                        reserve - debit,
                        fork.gas_units,
                        gas_wei,
                        gas_usd,
                        (*prefix, *route),
                        tuple(fork.transactions),
                    )
            reserve = max(reserve or 0, debit)
            candidate = budget - reserve
        raise Unavailable("gas funding did not converge for the selected route")

    def enter(
        self, block: Block, verified: VerifiedStrategy, source: Token, amount: int
    ) -> Execution:
        def calculate() -> Execution:
            with Fork(self.archive, block) as fork:
                fork.seed(source, amount)
                return self.funded_deposit(
                    fork, Router(fork, self.prices), verified, source, amount
                )

        return self.cached(
            "enter",
            block,
            {"strategy": asdict(verified), "source": asdict(source), "amount": amount},
            calculate,
        )

    def exit(
        self,
        block: Block,
        verified: VerifiedStrategy,
        target: Token,
        shares: int,
        baseline: Integrals | None,
        idle: dict[Token, int],
    ) -> Execution:
        def calculate() -> Execution:
            with Fork(self.archive, block) as fork:
                router = Router(fork, self.prices)
                route: tuple[str, ...] = ()
                rewards_output = 0
                rewards: dict[Token, int] = {}
                if baseline is not None:
                    seed_gauge(fork, verified, shares, baseline)
                    rewards = claim(fork, verified)
                else:
                    fork.seed(share_token(verified.strategy), shares)
                for token, amount in idle.items():
                    fork.seed(token, fork.balance(token) + amount)
                    rewards[token] = rewards.get(token, 0) + amount
                for token, reward_amount in rewards.items():
                    if reward_amount:
                        converted, path = router.convert(token, target, reward_amount)
                        rewards_output += converted
                        route += path
                amount, path = withdraw(fork, router, verified, target, shares)
                output = amount + rewards_output
                _, gas_usd = self.costs(block, fork.gas_units)
                price = self.prices.at(target, block.timestamp).usd
                debit = target.units(gas_usd / price, round_up=True)
                if output <= debit:
                    raise Unaffordable("withdrawal proceeds cannot cover exit gas")
                return self.execution(fork, output - debit, 0, (*route, *path))

        return self.cached(
            "exit",
            block,
            {
                "strategy": asdict(verified),
                "target": asdict(target),
                "shares": shares,
                "baseline": asdict(baseline) if baseline else None,
                "idle": [(asdict(t), n) for t, n in idle.items()],
            },
            calculate,
        )

    def compound(
        self,
        block: Block,
        verified: VerifiedStrategy,
        shares: int,
        baseline: Integrals,
        idle: dict[Token, int],
    ) -> Execution:
        def calculate() -> Execution:
            with Fork(self.archive, block) as fork:
                seed_gauge(fork, verified, shares, baseline)
                router = Router(fork, self.prices)
                proceeds = 0
                route: tuple[str, ...] = ()
                coin = deposit_coin(verified.strategy, CRV)
                for token, amount in claim(fork, verified).items():
                    if amount:
                        output, path = router.convert(token, coin, amount)
                        proceeds += output
                        route += path
                for token, amount in idle.items():
                    fork.seed(token, fork.balance(token) + amount)
                    output, path = router.convert(token, coin, amount)
                    proceeds += output
                    route += path
                if not proceeds:
                    raise Unaffordable("no rewards to compound")
                result = self.funded_deposit(
                    fork, router, verified, coin, proceeds, route
                )
                # Keep unused gas funding in the reward asset.
                return result

        return self.cached(
            "compound",
            block,
            {
                "strategy": asdict(verified),
                "shares": shares,
                "baseline": asdict(baseline),
                "idle": [(asdict(t), n) for t, n in idle.items()],
            },
            calculate,
        )

    def accounting(
        self, block: Block, verified: VerifiedStrategy, shares: int
    ) -> Decimal:
        def calculate() -> str:
            with Fork(self.archive, block) as fork:
                underlying = accounting_assets(fork, verified.strategy, shares)
                price = self.prices.at(
                    verified.strategy.underlying, block.timestamp
                ).usd
                return str(verified.strategy.underlying.quantity(underlying) * price)

        return Decimal(
            self.evidence(
                "accounting-v1",
                block,
                [asdict(verified), shares],
                calculate,
            )
        )
