"""Scenario inputs and accounting records, independent of presentation."""

from calendar import monthrange
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_CEILING, ROUND_DOWN, Decimal, localcontext


class Unavailable(Exception):
    """A result cannot be established from the available historical evidence."""


class Unaffordable(Unavailable):
    """A supported action has insufficient proceeds to pay its costs."""


class Reverted(Unavailable):
    """A contract rejected the hypothetical action at the selected block."""


class DepositLimit(Unavailable):
    """The requested underlying amount exceeds a known deposit capacity."""

    def __init__(self, requested: int, capacity: int):
        self.capacity = max(0, capacity)
        super().__init__(
            f"Yearn deposit amount {requested} exceeds historical capacity "
            f"{self.capacity} underlying units"
        )


@dataclass(frozen=True)
class Token:
    symbol: str = field(compare=False)
    address: str
    decimals: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "address", self.address.lower())

    @property
    def price_id(self) -> str:
        if self.address == "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee":
            return "coingecko:ethereum"
        return f"ethereum:{self.address.lower()}"

    def quantity(self, amount: int) -> Decimal:
        with localcontext() as ctx:
            ctx.prec = 100
            return Decimal(amount) / 10**self.decimals

    def units(self, quantity: Decimal, *, round_up: bool = False) -> int:
        with localcontext() as ctx:
            ctx.prec = 100
            return int(
                (quantity * 10**self.decimals).to_integral_value(
                    rounding=ROUND_CEILING if round_up else ROUND_DOWN
                )
            )


@dataclass(frozen=True)
class Block:
    number: int
    hash: str
    timestamp: int

    @property
    def date(self) -> str:
        return datetime.fromtimestamp(self.timestamp, UTC).isoformat()


@dataclass(frozen=True)
class Price:
    usd: Decimal
    timestamp: int
    source: str


@dataclass(frozen=True)
class Scenario:
    start: int
    end: int
    assets: tuple[str, ...] = ("USD", "BTC", "ETH", "CRV")
    usd_value: Decimal = Decimal(10000)

    def __post_init__(self) -> None:
        if self.start >= self.end:
            raise ValueError("start must precede end")
        if not self.usd_value.is_finite() or self.usd_value <= 0:
            raise ValueError("usd-value must be a finite positive number")
        if not self.assets or len(set(self.assets)) != len(self.assets):
            raise ValueError("assets must be nonempty and unique")
        if set(self.assets) - {"USD", "BTC", "ETH", "CRV"}:
            raise ValueError("assets must be USD, BTC, ETH, or CRV")


@dataclass(frozen=True)
class Action:
    timestamp: int
    block: Block
    kind: str
    gas_units: int = 0
    gas_wei: int = 0
    gas_usd: Decimal = Decimal(0)
    route: tuple[str, ...] = ()
    note: str = ""


@dataclass
class Position:
    shares: int
    start_dust: int = 0
    idle: dict[Token, int] = field(default_factory=dict)


@dataclass(frozen=True)
class Observation:
    strategy: str
    asset: str
    target: int
    block: Block
    status: str
    start_quantity: Decimal | None = None
    end_quantity: Decimal | None = None
    end_usd: Decimal | None = None
    net_return: Decimal | None = None
    versus_hold_usd: Decimal | None = None
    gas_usd: Decimal | None = None
    accounting_usd: Decimal | None = None
    note: str = ""
    route: tuple[str, ...] = ()


def parse_date(value: str) -> int:
    """Date-only input means midnight UTC; timestamps must specify a timezone."""
    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if date.tzinfo is None:
        if len(value) != 10:
            raise ValueError("timestamps must include a timezone; dates use UTC")
        date = date.replace(tzinfo=UTC)
    return int(date.timestamp())


def anniversaries(start: int, end: int) -> tuple[int, ...]:
    """Clamp each month against the original day, including leap years."""
    date = datetime.fromtimestamp(start, UTC)
    dates = []
    offset = 1
    while True:
        year, month = divmod(date.year * 12 + date.month - 1 + offset, 12)
        month += 1
        point = int(
            date.replace(
                year=year, month=month, day=min(date.day, monthrange(year, month)[1])
            ).timestamp()
        )
        if point >= end:
            return (*dates, end)
        dates.append(point)
        offset += 1


def v2_free_funds(
    total_assets: int,
    locked_profit: int,
    last_report: int,
    degradation: int,
    timestamp: int,
) -> int:
    elapsed = timestamp - last_report
    if elapsed < 0:
        raise Unavailable("lastReport is after the observation block")
    ratio = elapsed * degradation
    locked = 0 if ratio >= 10**18 else locked_profit - ratio * locked_profit // 10**18
    if locked > total_assets:
        raise Unavailable("locked profit exceeds total assets")
    return total_assets - locked


def v2_deposit_shares(assets: int, supply: int, free_funds: int) -> int:
    if assets < 0 or supply < 0 or free_funds < 0:
        raise ValueError("negative vault accounting input")
    if not supply:
        return assets
    if not free_funds:
        raise Unavailable("vault has supply but no free funds")
    return assets * supply // free_funds


def v2_share_value(shares: int, supply: int, free_funds: int) -> int:
    if min(shares, supply, free_funds) < 0:
        raise ValueError("negative vault accounting input")
    if not supply:
        raise Unavailable("vault has no outstanding shares")
    return shares * free_funds // supply


def reward_accrual(shares: int, before: int, after: int, *, crv: bool) -> int:
    if min(shares, before, after) < 0 or after < before:
        raise Unavailable("reward integral decreased; accounting needs investigation")
    balance = shares * 40 // 100 if crv else shares
    return balance * (after - before) // 10**18
