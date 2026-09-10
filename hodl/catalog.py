"""Fixed contracts. State verification, not present-day rankings, gates a run."""

from dataclasses import dataclass

from hodl.data import Archive
from hodl.model import Block, Token, Unavailable

ETH = Token("ETH", "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE", 18)
USDC = Token("USDC", "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", 6)
WBTC = Token("WBTC", "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599", 8)
WETH = Token("WETH", "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", 18)
CRV = Token("CRV", "0xD533a949740bb3306d119CC777fa900bA034cd52", 18)
DAI = Token("DAI", "0x6B175474E89094C44Da98b954EedeAC495271d0F", 18)
USDT = Token("USDT", "0xdAC17F958D2ee523a2206206994597C13D831ec7", 6)
STETH = Token("stETH", "0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84", 18)
CVXCRV = Token("cvxCRV", "0x62B9c7356A2Dc64a1969e19C23e4f579F9810Aa7", 18)
CURVE_FACTORY = "0xB9fC157394Af804a3578134A6585C0dc9cc990d4"
ADDRESS_PROVIDER = "0x0000000022D53366457F9d5E68Ec105046FC4383"
MINTER = "0xd061D61a4d941c39E5453435B6345Dc261C2fcE0"
ZERO = "0x0000000000000000000000000000000000000000"


def assets() -> dict[str, Token]:
    return {"USD": USDC, "BTC": WBTC, "ETH": ETH, "CRV": CRV}


@dataclass(frozen=True)
class Pool:
    name: str
    address: str
    lp: Token
    coins: tuple[Token, ...]
    version: str
    gauge: str | None
    gauge_version: str

    @property
    def index_type(self) -> str:
        return "uint256" if self.version == "crypto-v2" else "int128"


@dataclass(frozen=True)
class Strategy:
    name: str
    address: str
    kind: str
    version: str
    underlying: Token
    pool: Pool | None = None
    gauge: str | None = None


@dataclass(frozen=True)
class VerifiedStrategy:
    strategy: Strategy
    deployment: Block
    gauge: str | None
    gauge_deployment: Block | None
    code_hash: str
    lp_deployment: Block | None = None
    gauge_code_hash: str | None = None


def pools() -> tuple[Pool, ...]:
    return (
        Pool(
            "3pool",
            "0xbEbc44782C7dB0a1A60Cb6fe97d0b483032FF1C7",
            Token("3Crv", "0x6c3F90f043a72FA612cbac8115EE7e52BDe6E490", 18),
            (DAI, USDC, USDT),
            "stable-v1",
            "0xbFcF63294aD7105dEa65aA58F8AE5BE2D9d0952A",
            "original",
        ),
        Pool(
            "tricrypto2",
            "0xD51a44d3FaE010294C616388b506AcdA1bfAAE46",
            Token("crv3crypto", "0xc4AD29ba4B3c580e6D59105FFf484999997675Ff", 18),
            (USDT, WBTC, WETH),
            "crypto-v2",
            "0xDeFd8FdD20e0f34115C7018CCfb655796F6B2168",
            "v3",
        ),
        Pool(
            "eth-steth",
            "0xDC24316b9AE028F1497c275EB9192a3Ea0f67022",
            Token("steCRV", "0x06325440D014e39736583c165C2963BA99fAf14E", 18),
            (ETH, STETH),
            "stable-eth",
            "0x182B723a58739a9c974cFDB385ceaDb237453c28",
            "v2",
        ),
        Pool(
            "crv-cvxcrv-v2",
            "0x971add32Ea87f10bD192671630be3BE8A11b8623",
            Token("cvxcrv-crv-f", "0x971add32Ea87f10bD192671630be3BE8A11b8623", 18),
            (CRV, CVXCRV),
            "factory-plain",
            None,
            "factory",
        ),
    )


def strategies() -> tuple[Strategy, ...]:
    three, tri, steth, cvx = pools()
    curve = tuple(
        Strategy(
            f"curve-{p.name}-{kind}",
            p.address,
            kind,
            p.version,
            p.lp,
            p,
            p.gauge if kind == "gauge" else None,
        )
        for p in (three, tri, steth, cvx)
        for kind in ("lp", "gauge")
    )
    vaults = (
        ("usdc-v2", "0xa354F35829Ae975e850e23e9615b11Da1B3dC4DE", "0.4.3", USDC, None),
        ("wbtc-v2", "0xA696a63cc78DfFa1a63E9E50587C197387FF6C7E", "0.3.5", WBTC, None),
        ("weth-v2", "0xa258C4606Ca8206D8aA700cE2143D7db854D168c", "0.4.2", WETH, None),
        (
            "tricrypto2-v2",
            "0xE537B5cc158EB71037D4125BDD7538421981E6AA",
            "0.4.3",
            tri.lp,
            tri,
        ),
        (
            "crv-cvxcrv-v2",
            "0xa8eF50905352aCD611F53640b001E48F2eA31d63",
            "0.4.6",
            cvx.lp,
            cvx,
        ),
        ("usd-v3", "0x696d02Db93291651ED510704c9b286841d506987", "3.0.4", USDC, None),
    )
    return curve + tuple(
        Strategy(
            "yearn-" + name,
            address,
            "v3" if version.startswith("3.") else "v2",
            version,
            token,
            pool,
        )
        for name, address, version, token, pool in vaults
    )


def verify(archive: Archive, strategy: Strategy, block: Block) -> VerifiedStrategy:
    from web3 import Web3

    deployed = archive.deployment(strategy.address, block)
    code = archive.code(block, strategy.address)
    if code == "0x":
        raise Unavailable(f"{strategy.name} has no code at block {block.number}")
    if strategy.kind in ("v2", "v3"):
        method = "token()" if strategy.kind == "v2" else "asset()"
        underlying = archive.call(block, strategy.address, method, returns=("address",))
        if underlying.lower() != strategy.underlying.address.lower():
            raise Unavailable("vault underlying differs from the fixed catalog")
        for address in (strategy.address, underlying):
            if (
                archive.call(block, address, "decimals()")
                != strategy.underlying.decimals
            ):
                raise Unavailable(
                    "vault or underlying decimals differ from the catalog"
                )
        version = archive.call(
            block, strategy.address, "apiVersion()", returns=("string",)
        )
        if version != strategy.version:
            raise Unavailable(
                f"unverified vault version: {version}; expected {strategy.version}"
            )
    if strategy.pool:
        pool = strategy.pool
        if pool.version == "crypto-v2":
            linked_lp = archive.call(
                block, pool.address, "token()", returns=("address",)
            )
            if linked_lp.lower() != pool.lp.address.lower():
                raise Unavailable("pool LP token differs from the catalog")
        elif pool.lp.address.lower() != pool.address.lower():
            registry = archive.call(
                block, ADDRESS_PROVIDER, "get_registry()", returns=("address",)
            )
            linked_lp = archive.call(
                block,
                registry,
                "get_lp_token(address)",
                ("address",),
                (pool.address,),
                ("address",),
            )
            if linked_lp.lower() != pool.lp.address:
                raise Unavailable("historical registry LP differs from the catalog")
        for index, coin in enumerate(strategy.pool.coins):
            actual = archive.call(
                block,
                strategy.pool.address,
                "coins(uint256)",
                ("uint256",),
                (index,),
                ("address",),
            )
            if actual.lower() != coin.address.lower():
                raise Unavailable(f"pool coin {index} differs from the catalog")
            if (
                coin != ETH
                and archive.call(block, actual, "decimals()") != coin.decimals
            ):
                raise Unavailable(f"pool coin {index} decimals differ from the catalog")
        decimals = archive.call(block, strategy.pool.lp.address, "decimals()")
        if decimals != strategy.pool.lp.decimals:
            raise Unavailable("LP decimals differ from the catalog")
    gauge = strategy.gauge if strategy.kind == "gauge" else None
    gauge_deployed = None
    gauge_code_hash = None
    if strategy.kind == "gauge":
        if gauge is None:
            gauge = archive.call(
                block,
                CURVE_FACTORY,
                "get_gauge(address)",
                ("address",),
                (strategy.address,),
                ("address",),
            )
        if gauge.lower() == ZERO:
            raise Unavailable("no gauge exists at the entry block")
        gauge_deployed = archive.deployment(gauge, block)
        gauge_code_hash = Web3.keccak(hexstr=archive.code(block, gauge)).to_0x_hex()
        lp = archive.call(block, gauge, "lp_token()", returns=("address",))
        if lp.lower() != strategy.underlying.address.lower():
            raise Unavailable("gauge LP token differs from the catalog")
    lp_deployment = (
        archive.deployment(strategy.pool.lp.address, block) if strategy.pool else None
    )
    return VerifiedStrategy(
        strategy,
        deployed,
        gauge,
        gauge_deployed,
        Web3.keccak(hexstr=code).to_0x_hex(),
        lp_deployment,
        gauge_code_hash,
    )
