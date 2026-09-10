"""Pinned mainnet reads and timestamp-bounded historical token prices."""

import hashlib
import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from eth_abi import decode, encode
from web3 import HTTPProvider, Web3

from hodl.cache import Cache
from hodl.model import Block, Price, Token, Unavailable


def calldata(signature: str, types: tuple[str, ...] = (), args: tuple = ()) -> str:
    return "0x" + (Web3.keccak(text=signature)[:4] + encode(types, args)).hex()


def last_block_at(
    timestamp: int, ceiling: Block, read: Callable[[int], Block]
) -> Block:
    if timestamp >= ceiling.timestamp:
        return ceiling
    low, high = 0, ceiling.number
    while low < high:
        mid = (low + high + 1) // 2
        if read(mid).timestamp <= timestamp:
            low = mid
        else:
            high = mid - 1
    result = read(low)
    if result.timestamp > timestamp:
        raise Unavailable("requested date precedes Ethereum genesis")
    return result


class Archive:
    def __init__(self, url: str, cache: Cache):
        self.url = url
        self.cache = cache
        # Retain source identity without writing provider credentials to the cache.
        self.source = "ethereum-rpc:sha256:" + hashlib.sha256(url.encode()).hexdigest()
        self.provider = HTTPProvider(url, request_kwargs={"timeout": 45})

    def request(self, method: str, params: list) -> Any:
        try:
            response = self.provider.make_request(method, params)
        except Exception as exc:
            raise Unavailable(f"archive RPC transport failed for {method}") from exc
        if "error" in response:
            error = response["error"]
            raise Unavailable(f"archive RPC {method}: {error}")
        if response.get("result") is None and method not in (
            "eth_getTransactionReceipt",
            "eth_getTransactionByHash",
        ):
            raise Unavailable(f"archive RPC returned no result for {method}")
        return response["result"]

    def rpc(self, method: str, params: list, block_hash: str | None = None) -> Any:
        return self.cache.get(
            "rpc-v1",
            [method, params],
            self.source,
            lambda: self.request(method, params),
            block_hash=block_hash,
        )

    @staticmethod
    def block_record(raw: dict) -> Block:
        return Block(int(raw["number"], 16), raw["hash"], int(raw["timestamp"], 16))

    def finalized(self) -> Block:
        if self.cache.offline:
            raise Unavailable("offline runs require an explicit end date")
        self.check_mainnet()
        return self.block_record(
            self.request("eth_getBlockByNumber", ["finalized", False])
        )

    def check_mainnet(self) -> None:
        if int(self.request("eth_chainId", []), 16) != 1:
            raise Unavailable("RPC must serve Ethereum mainnet (chain ID 1)")

    def block(self, number: int) -> Block:
        raw = self.rpc("eth_getBlockByNumber", [hex(number), False])
        return self.block_record(raw)

    def at(self, timestamp: int, ceiling: Block) -> Block:
        raw = self.cache.get(
            "timestamp-v1",
            timestamp,
            self.source,
            lambda: vars(last_block_at(timestamp, ceiling, self.block)),
        )
        result = Block(**raw)
        if result.number > ceiling.number:
            raise Unavailable("cached timestamp resolution exceeds finalized head")
        return result

    def call(
        self,
        block: Block,
        address: str,
        signature: str,
        types: tuple[str, ...] = (),
        args: tuple = (),
        returns: tuple[str, ...] = ("uint256",),
    ) -> Any:
        data = self.rpc(
            "eth_call",
            [
                {"to": address, "data": calldata(signature, types, args)},
                {"blockHash": block.hash, "requireCanonical": True},
            ],
            block.hash,
        )
        try:
            result = decode(returns, bytes.fromhex(data.removeprefix("0x")))
        except Exception as exc:
            raise Unavailable(
                f"cannot decode {address} {signature} at {block.number}"
            ) from exc
        return result[0] if len(result) == 1 else result

    def code(self, block: Block, address: str) -> str:
        return self.rpc(
            "eth_getCode",
            [
                address,
                {
                    "blockHash": block.hash,
                    "requireCanonical": True,
                },
            ],
            block.hash,
        )

    def deployment(self, address: str, ceiling: Block) -> Block:
        def find() -> dict:
            if self.code(ceiling, address) == "0x":
                raise Unavailable(f"no contract at {address} by block {ceiling.number}")
            low, high = 0, ceiling.number
            while low < high:
                mid = (low + high) // 2
                if self.code(self.block(mid), address) == "0x":
                    low = mid + 1
                else:
                    high = mid
            return vars(self.block(low))

        return Block(
            **self.cache.get("deployment-v1", address.lower(), self.source, find)
        )

    def logs(self, address: str, start: Block, end: Block, topics: list) -> list[dict]:
        result = []
        for first in range(start.number, end.number + 1, 2000):
            last = min(first + 1999, end.number)
            result.extend(
                self.rpc(
                    "eth_getLogs",
                    [
                        {
                            "address": address,
                            "fromBlock": hex(first),
                            "toBlock": hex(last),
                            "topics": topics,
                        }
                    ],
                    self.block(last).hash,
                )
            )
        return result

    def gas_price(self, block: Block) -> int:
        raw = self.rpc("eth_getBlockByHash", [block.hash, True], block.hash)
        base = int(raw.get("baseFeePerGas", "0x0"), 16)
        prices = []
        for tx in raw["transactions"]:
            if "maxFeePerGas" in tx and tx["maxFeePerGas"] is not None:
                effective = min(
                    int(tx["maxFeePerGas"], 16),
                    base + int(tx["maxPriorityFeePerGas"], 16),
                )
            else:
                effective = int(tx["gasPrice"], 16)
            prices.append(
                max(0, effective - base) if "baseFeePerGas" in raw else effective
            )
        if not prices:
            raise Unavailable(f"block {block.number} has no gas price observations")
        prices.sort()
        middle = len(prices) // 2
        priority = (
            prices[middle]
            if len(prices) % 2
            else (prices[middle - 1] + prices[middle] + 1) // 2
        )
        return base + priority


def select_price(points: list[dict], timestamp: int, source: str) -> Price:
    eligible = [
        point
        for point in points
        if timestamp - 86400 <= int(point["timestamp"]) <= timestamp
    ]
    if not eligible:
        raise Unavailable("no historical price at or before the target within 24 hours")
    selected = max(eligible, key=lambda p: int(p["timestamp"]))
    value = Decimal(str(selected["price"]))
    if not value.is_finite() or value <= 0:
        raise Unavailable("historical price is not a finite positive number")
    return Price(value, int(selected["timestamp"]), source)


class Prices:
    def __init__(self, cache: Cache):
        self.cache = cache

    def at(self, token: Token, timestamp: int) -> Price:
        # A chart window supplies earlier points even when the closest point is later.
        url = (
            f"https://coins.llama.fi/chart/{token.price_id}"
            f"?start={timestamp - 86400}&period=1h&span=25"
        )

        def fetch() -> dict:
            try:
                with urlopen(url, timeout=45) as response:
                    return json.loads(response.read(), parse_float=str)
            except (URLError, ValueError) as exc:
                raise Unavailable(
                    f"DefiLlama historical price request failed: {token.symbol}"
                ) from exc

        raw = self.cache.get("prices-v1", url, "https://coins.llama.fi", fetch)
        points = raw.get("coins", {}).get(token.price_id, {}).get("prices", [])
        return select_price(points, timestamp, url)
