"""Search bounded Curve/Uniswap V3 and liquid-locker mint routes at the block."""

from dataclasses import dataclass
from decimal import Decimal

from hodl.catalog import (
    CRV,
    CVXCRV,
    ETH,
    SDCRV,
    USDC,
    USDT,
    WBTC,
    WETH,
    YCRV,
    ZERO,
    Pool,
    routing_pools,
)
from hodl.data import Prices
from hodl.fork import ACCOUNT, Fork
from hodl.model import Reverted, Token, Unaffordable, Unavailable

FACTORY = "0x1F98431c8aD98523631AE4a59f267346ea31F984"
QUOTER = "0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6"
ROUTER = "0xE592427A0AEce92De3Edee1F18E0157C05861564"


@dataclass(frozen=True)
class Mint:
    token: Token
    address: str
    signature: str
    types: tuple[str, ...]
    args: tuple


def mint_route(fork: Fork, token: Token) -> Mint | None:
    if token not in (YCRV, CVXCRV, SDCRV):
        return None
    if fork.rpc("eth_getCode", [token.address, "latest"]) == "0x":
        return None
    if token == YCRV:
        return Mint(
            token,
            token.address,
            "mint(uint256,address)",
            ("uint256", "address"),
            (ACCOUNT,),
        )
    if token == CVXCRV:
        return Mint(
            token,
            "0x8014595F2AB54cD7c604B00E9fb932176fDc86Ae",
            "deposit(uint256,bool)",
            ("uint256", "bool"),
            (True,),
        )
    # sdCRV changed depositors. Resolve its authorized operator at this block.
    operator = fork.call(token.address, "operator()", returns=("address",))
    for getter, expected in (("token()", CRV), ("minter()", SDCRV)):
        actual = fork.call(operator, getter, returns=("address",))
        if actual.lower() != expected.address:
            raise Unavailable("unverified sdCRV depositor tokens")
    # These deployed generations have different public deposit interfaces.
    if operator.lower() == "0xc1e3ca8a3921719be0ae3690a0e036feb4f69191":
        return Mint(
            token,
            operator,
            "deposit(uint256,bool,bool,address)",
            ("uint256", "bool", "bool", "address"),
            (True, False, ACCOUNT),
        )
    if operator.lower() == "0xa50cb9dffcc740ee6b6f2d4b3cbc3a876b28c335":
        return Mint(
            token,
            operator,
            "deposit(uint256,address)",
            ("uint256", "address"),
            (ACCOUNT,),
        )
    raise Unavailable(f"unverified sdCRV mint operator: {operator}")


@dataclass(frozen=True)
class Hop:
    source: Token
    target: Token
    pool: Pool | None = None
    fee: int = 0
    mint: Mint | None = None

    @property
    def label(self) -> str:
        if self.mint:
            return f"CRV -> {self.target.symbol} (mint {self.mint.address})"
        venue = (
            f"Curve {self.pool.name} {self.pool.address}"
            if self.pool
            else f"Uniswap V3 fee={self.fee} router={ROUTER}"
        )
        return f"{self.source.symbol} -> {self.target.symbol} ({venue})"


@dataclass(frozen=True)
class Route:
    hops: tuple[Hop, ...]
    output: int
    gas_units: int
    net_usd: Decimal


def canonical(token: Token) -> Token:
    return WETH if token == ETH else token


class Router:
    def __init__(self, fork: Fork, prices: Prices):
        self.fork = fork
        self.prices = prices
        self.available: dict[tuple[Token, Token], tuple[Hop, ...]] = {}

    def hops(self, source: Token, target: Token) -> tuple[Hop, ...]:
        key = (source, target)
        if key in self.available:
            return self.available[key]
        result = []
        mint = mint_route(self.fork, target) if source == CRV else None
        if mint is not None:
            if self.fork.rpc("eth_getCode", [mint.address, "latest"]) != "0x":
                result.append(Hop(source, target, mint=mint))
        for pool in routing_pools():
            coins = tuple(canonical(c) for c in pool.coins)
            if (source in coins or source == pool.lp) and target in coins:
                code = self.fork.rpc("eth_getCode", [pool.address, "latest"])
                if code != "0x":
                    result.append(
                        Hop(
                            source
                            if source == pool.lp
                            else pool.coins[coins.index(source)],
                            pool.coins[coins.index(target)],
                            pool,
                        )
                    )
        if self.fork.rpc("eth_getCode", [FACTORY, "latest"]) != "0x":
            for fee in (100, 500, 3000, 10000):
                address = self.fork.call(
                    FACTORY,
                    "getPool(address,address,uint24)",
                    ("address", "address", "uint24"),
                    (source.address, target.address, fee),
                    ("address",),
                )
                if address.lower() != ZERO:
                    result.append(Hop(source, target, fee=fee))
        self.available[key] = tuple(result)
        return tuple(result)

    def execute_hop(self, hop: Hop, amount: int) -> int:
        before = self.fork.balance(hop.target)
        gas_before = self.fork.gas_units
        if hop.mint:
            mint = hop.mint
            source_before = self.fork.balance(hop.source)
            self.fork.approve(hop.source, mint.address, amount)
            self.fork.transact(
                mint.address,
                mint.signature,
                mint.types,
                (amount, *mint.args),
                label=hop.label,
            )
            if source_before - self.fork.balance(hop.source) != amount:
                raise Reverted("mint did not spend the requested CRV amount")
        elif hop.pool:
            pool = hop.pool
            if hop.source == pool.lp:
                self.fork.transact(
                    pool.address,
                    f"remove_liquidity_one_coin(uint256,{pool.index_type},uint256)",
                    ("uint256", pool.index_type, "uint256"),
                    (amount, pool.coins.index(hop.target), 0),
                    label=hop.label,
                )
                output = self.fork.balance(hop.target) - before
                if hop.target == ETH:
                    output += (
                        self.fork.gas_units - gas_before
                    ) * self.fork.archive.gas_price(self.fork.block)
                if output <= 0:
                    raise Unaffordable("LP redemption rounds to zero")
                return output
            i, j = pool.coins.index(hop.source), pool.coins.index(hop.target)
            index_type = pool.index_type
            quote = self.fork.call(
                pool.address,
                f"get_dy({index_type},{index_type},uint256)",
                (index_type, index_type, "uint256"),
                (i, j, amount),
            )
            if quote <= 0:
                raise Unaffordable("Curve swap quote rounds to zero")
            self.fork.approve(hop.source, pool.address, amount)
            signature = f"exchange({index_type},{index_type},uint256,uint256)"
            types = (index_type, index_type, "uint256", "uint256")
            args = (i, j, amount, 0)
            if pool.version == "crypto-v2":
                signature = "exchange(uint256,uint256,uint256,uint256,bool)"
                types = (*types, "bool")
                args = (*args, False)
            self.fork.transact(
                pool.address,
                signature,
                types,
                args,
                value=amount if hop.source == ETH else 0,
                label=hop.label,
            )
        else:
            source_before = self.fork.balance(hop.source)
            quote = self.fork.call(
                QUOTER,
                "quoteExactInputSingle(address,address,uint24,uint256,uint160)",
                ("address", "address", "uint24", "uint256", "uint160"),
                (hop.source.address, hop.target.address, hop.fee, amount, 0),
            )
            if quote <= 0:
                raise Unaffordable("Uniswap swap quote rounds to zero")
            self.fork.approve(hop.source, ROUTER, amount)
            self.fork.transact(
                ROUTER,
                "exactInputSingle((address,address,uint24,address,uint256,uint256,uint256,uint160))",
                ("(address,address,uint24,address,uint256,uint256,uint256,uint160)",),
                (
                    (
                        hop.source.address,
                        hop.target.address,
                        hop.fee,
                        ACCOUNT,
                        self.fork.block.timestamp,
                        amount,
                        0,
                        0,
                    ),
                ),
                label=hop.label,
            )
            spent = source_before - self.fork.balance(hop.source)
            if spent != amount:
                raise Reverted(
                    f"partial Uniswap V3 fill: requested {amount}, spent {spent} "
                    f"{hop.source.symbol} units on {hop.label}"
                )
        output = self.fork.balance(hop.target) - before
        if hop.target == ETH:
            output += (self.fork.gas_units - gas_before) * self.fork.archive.gas_price(
                self.fork.block
            )
        if output <= 0:
            raise Reverted("swap produced no output")
        return output

    def execute(
        self, source: Token, target: Token, amount: int, hops: tuple[Hop, ...]
    ) -> int:
        if source == target:
            return amount
        output = amount
        held = source
        for hop in hops:
            self.wrap_between(held, hop.source, output)
            output = self.execute_hop(hop, output)
            held = hop.target
        self.wrap_between(held, target, output)
        return output

    def wrap_between(self, source: Token, target: Token, amount: int) -> None:
        if source == target:
            return
        if source == ETH and target == WETH:
            self.fork.wrap(amount)
        elif source == WETH and target == ETH:
            self.fork.unwrap(amount)
        else:
            raise ValueError("route contains disconnected tokens")

    def best(self, source: Token, target: Token, amount: int) -> Route:
        if amount <= 0:
            raise Unavailable("conversion input is zero")
        price = self.prices.at(target, self.fork.block.timestamp).usd
        if source == target:
            return Route((), amount, 0, target.quantity(amount) * price)
        a, b = canonical(source), canonical(target)
        candidates = [()] if a == b else self.candidate_paths(a, b)
        gas_price = self.fork.archive.gas_price(self.fork.block)
        eth_price = self.prices.at(ETH, self.fork.block.timestamp).usd
        best = None
        failures = []
        insufficient = []
        for path in candidates:
            with self.fork.snapshot():
                gas_before = self.fork.gas_units
                try:
                    output = self.execute(source, target, amount, path)
                    gas = self.fork.gas_units - gas_before
                except Reverted as exc:
                    failures.append(str(exc))
                    continue
                except Unaffordable as exc:
                    insufficient.append(str(exc))
                    continue
                net = (
                    target.quantity(output) * price
                    - Decimal(gas * gas_price) / 10**18 * eth_price
                )
                route = Route(path, output, gas, net)
                if best is None or route.net_usd > best.net_usd:
                    best = route
        if best is None:
            if insufficient:
                raise Unaffordable(
                    f"conversion {source.symbol}->{target.symbol} is too small: "
                    + insufficient[0]
                )
            reason = (
                failures[0] if failures else "no deployed pool connects these tokens"
            )
            raise Unavailable(
                f"no supported route {source.symbol}->{target.symbol}: {reason}"
            )
        return best

    def candidate_paths(self, source: Token, target: Token) -> list[tuple[Hop, ...]]:
        """All simple paths with at most three steps through fixed intermediates."""

        def visit(current: Token, seen: tuple[Token, ...], path: tuple[Hop, ...]):
            for hop in self.hops(current, target):
                yield (*path, hop)
            if len(path) < 2:
                for via in (WETH, USDC, USDT, WBTC, CRV):
                    if via not in (*seen, target):
                        for hop in self.hops(current, via):
                            yield from visit(via, (*seen, via), (*path, hop))

        return list(visit(source, (source,), ()))

    def convert(
        self, source: Token, target: Token, amount: int
    ) -> tuple[int, tuple[str, ...]]:
        best = self.best(source, target, amount)
        before = len(self.fork.transactions)
        output = self.execute(source, target, amount, best.hops)
        labels = tuple(tx["label"] for tx in self.fork.transactions[before:])
        return output, labels
