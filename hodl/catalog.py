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
YCRV = Token("yCRV", "0xFCc5c47bE19d06BF83eB04298b026F81069ff65b", 18)
SDCRV = Token("sdCRV", "0xD1b5651E55D4CeeD36251c61c50C889B36F6abB5", 18)
CVX = Token("CVX", "0x4e3FBD56CD56c3e72c1403e103b45Db9da5B9D2B", 18)
SDT = Token("SDT", "0x73968b9a57c6E53d41345FD57a6E6ae27d6CDB2F", 18)
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
        Pool(
            "crv-ycrv-v2",
            "0x99f5aCc8EC2Da2BC0771c32814EFF52b712de1E5",
            Token("yCRV-f", "0x99f5aCc8EC2Da2BC0771c32814EFF52b712de1E5", 18),
            (CRV, YCRV),
            "factory-plain",
            None,
            "factory",
        ),
        Pool(
            "crv-sdcrv-v2",
            "0xCA0253A98D16e9C1e3614CaFDA19318EE69772D0",
            Token("sdCRV-f", "0xCA0253A98D16e9C1e3614CaFDA19318EE69772D0", 18),
            (CRV, SDCRV),
            "factory-plain",
            None,
            "factory",
        ),
    )


def routing_pools() -> tuple[Pool, ...]:
    """Position pools plus historical markets used to convert staking rewards."""
    return pools() + (
        Pool(
            "eth-cvx",
            "0xB576491F1E6e5E62f1d8F26062Ee822B40B0E0d4",
            Token("cvxeth", "0x3A283D9c08E8b55966afb64C515f5143cf907611", 18),
            (WETH, CVX),
            "crypto-v2",
            None,
            "",
        ),
        Pool(
            "eth-sdt",
            "0xfB8814D005C5f32874391e888da6eB2fE7a27902",
            Token("sdteth", "0x6359B6d3e327c497453d4376561eE276c6933323", 18),
            (WETH, SDT),
            "crypto-v2",
            None,
            "",
        ),
        Pool(
            "crv-ycrv-v1",
            "0x453D92C7d4263201C69aACfaf589Ed14202d83a4",
            Token("yCRV-f-v1", "0x453D92C7d4263201C69aACfaf589Ed14202d83a4", 18),
            (CRV, YCRV),
            "factory-plain",
            None,
            "factory",
        ),
    )


def strategies() -> tuple[Strategy, ...]:
    three, tri, steth, cvx, ycrv, sdcrv = pools()
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
        for p in (three, tri, steth, cvx, ycrv, sdcrv)
        for kind in ("lp", "gauge")
    )
    vaults = (
        ("usdc-v2", "0xa354F35829Ae975e850e23e9615b11Da1B3dC4DE", "0.4.3", USDC, None),
        ("wbtc-v2", "0xA696a63cc78DfFa1a63E9E50587C197387FF6C7E", "0.3.5", WBTC, None),
        ("weth-v2", "0xa258C4606Ca8206D8aA700cE2143D7db854D168c", "0.4.2", WETH, None),
        (
            "eth-steth-v2",
            "0xdCD90C7f6324cfa40d7169ef80b12031770B4325",
            "0.3.0",
            steth.lp,
            steth,
        ),
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
        (
            "eth-steth-factory-v2",
            "0x5B8C556B8b2a78696F0B9B830B3d67623122E270",
            "0.4.5",
            steth.lp,
            steth,
        ),
        ("ycrv-v2", "0x27B5739e22ad9033bcBf192059122d163b60349D", "0.4.3", YCRV, None),
        (
            "crv-ycrv-v2",
            "0x6E9455D109202b426169F0d8f01A3332DAE160f3",
            "0.4.6",
            ycrv.lp,
            ycrv,
        ),
    )
    staking = (
        Strategy(
            "convex-cvxcrv-staked",
            "0xaa0C3f5F7DFD688C6E646F66CD2a6B66ACdbE434",
            "convex",
            "cvxcrv-wrapper-50-50",
            CVXCRV,
        ),
        Strategy(
            "stakedao-sdcrv-onchain",
            "0x7f50786A0b15723D741727882ee99a0BF34e3466",
            "stakedao",
            "sdcrv-gauge-no-vote-incentives",
            SDCRV,
        ),
    )
    return (
        curve
        + staking
        + tuple(
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
    if strategy.kind in ("convex", "stakedao"):
        getter = "cvxCrv()" if strategy.kind == "convex" else "staking_token()"
        underlying = archive.call(block, strategy.address, getter, returns=("address",))
        if underlying.lower() != strategy.underlying.address.lower():
            raise Unavailable("staking underlying differs from the fixed catalog")
        if (
            archive.call(block, underlying, "decimals()")
            != strategy.underlying.decimals
        ):
            raise Unavailable("staking token decimals differ from the fixed catalog")
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
