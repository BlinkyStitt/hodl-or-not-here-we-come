import json
from decimal import Decimal
from http.client import IncompleteRead
from unittest.mock import MagicMock

import pytest

from hodl.cache import Cache
from hodl.catalog import USDC
from hodl.data import Archive, Prices, last_block_at, select_price
from hodl.model import Block, Price, Unavailable


def test_rpc_accepts_pending_receipt_but_rejects_missing_block(tmp_path, monkeypatch):
    cache = Cache(tmp_path / "evidence.sqlite")
    archive = Archive("http://unused.invalid", cache)
    monkeypatch.setattr(
        archive.provider, "make_request", lambda method, params: {"result": None}
    )
    assert archive.request("eth_getTransactionReceipt", ["unknown-hash"]) is None
    with pytest.raises(Unavailable, match="no result"):
        archive.request("eth_getBlockByNumber", ["0x1", False])
    cache.close()


def test_last_block_never_selects_a_future_block():
    blocks = [
        Block(i, f"hash-{i}", timestamp)
        for i, timestamp in enumerate((100, 110, 140, 141, 180))
    ]
    for timestamp, expected in (
        (100, 0),
        (109, 0),
        (110, 1),
        (139, 1),
        (140, 2),
        (179, 3),
        (180, 4),
        (200, 4),
    ):
        assert (
            last_block_at(timestamp, blocks[-1], blocks.__getitem__) == blocks[expected]
        )
    with pytest.raises(Unavailable, match="genesis"):
        last_block_at(99, blocks[-1], blocks.__getitem__)


def test_price_selects_latest_prior_point_and_actual_stablecoin_price():
    selected = select_price(
        [
            {"timestamp": 999, "price": "0.88"},
            {"timestamp": 1001, "price": "1.00"},
            {"timestamp": 998, "price": "0.90"},
        ],
        1000,
        "source",
    )
    assert selected.usd == Decimal("0.88")
    assert selected.timestamp == 999
    assert selected.source == "source"


def test_price_age_includes_exact_24_hour_boundary():
    assert (
        select_price([{"timestamp": 13600, "price": 1}], 100000, "source").timestamp
        == 13600
    )
    for timestamp in (13599, 100001):
        with pytest.raises(Unavailable, match="24 hours"):
            select_price([{"timestamp": timestamp, "price": 1}], 100000, "source")


@pytest.mark.parametrize(
    "error",
    [TimeoutError("timed out"), ConnectionResetError("reset"), IncompleteRead(b"{")],
    ids=["timeout", "connection-reset", "incomplete-read"],
)
def test_price_read_failure_is_unavailable_and_can_be_retried(
    tmp_path, monkeypatch, error
):
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.side_effect = error
    monkeypatch.setattr("hodl.data.urlopen", lambda url, timeout: response)
    cache = Cache(tmp_path / "evidence.sqlite")
    prices = Prices(cache)
    try:
        with pytest.raises(Unavailable) as exc:
            prices.at(USDC, 100000)
        assert str(exc.value) == "DefiLlama historical price request failed: USDC"
        assert exc.value.__cause__ is error

        response.read.side_effect = None
        response.read.return_value = json.dumps(
            {
                "coins": {
                    USDC.price_id: {"prices": [{"timestamp": 100000, "price": 0.99}]}
                }
            }
        ).encode()
        assert prices.at(USDC, 100000) == Price(
            Decimal("0.99"),
            100000,
            f"https://coins.llama.fi/chart/{USDC.price_id}?start=13600&period=1h&span=25",
        )
    finally:
        cache.close()


def test_cache_preserves_hash_and_source_and_reproduces_offline(tmp_path):
    path = tmp_path / "evidence.sqlite"
    cache = Cache(path)
    assert cache.get(
        "call", [1], "source-a", lambda: {"value": 12}, block_hash="a"
    ) == {"value": 12}
    assert cache.get(
        "call", [1], "source-a", lambda: {"value": 13}, block_hash="b"
    ) == {"value": 13}
    cache.close()
    cache = Cache(path, offline=True)

    def forbidden():
        pytest.fail("offline cache called a data source")

    assert cache.get("call", [1], "source-a", forbidden, block_hash="a") == {
        "value": 12
    }
    with pytest.raises(Unavailable, match="cache miss"):
        cache.get("call", [1], "source-b", forbidden, block_hash="a")
    with pytest.raises(Unavailable, match="cache miss"):
        cache.get("call", [1], "source-a", forbidden, block_hash="c")
    cache.close()


def test_cache_does_not_store_a_failed_read(tmp_path):
    cache = Cache(tmp_path / "evidence.sqlite")

    def fail():
        raise Unavailable("archive unavailable")

    with pytest.raises(Unavailable):
        cache.get("call", 1, "rpc", fail)
    assert cache.get("call", 1, "rpc", lambda: 9) == 9
    cache.close()


def test_deployment_search_checks_code_boundary(tmp_path, monkeypatch):
    cache = Cache(tmp_path / "evidence.sqlite")
    archive = Archive("http://unused.invalid", cache)
    monkeypatch.setattr(
        archive, "block", lambda number: Block(number, str(number), number * 12)
    )
    monkeypatch.setattr(
        archive,
        "code",
        lambda block, address: "0x6000" if block.number >= 123 else "0x",
    )
    assert archive.deployment("contract", Block(500, "500", 6000)) == Block(
        123, "123", 1476
    )
    with pytest.raises(Unavailable, match="no contract"):
        archive.deployment("other", Block(122, "122", 1464))
    cache.close()


@pytest.mark.parametrize("known_later_deployment", [False, True])
def test_absent_contract_replays_offline_with_the_same_reason(
    tmp_path, monkeypatch, known_later_deployment
):
    path = tmp_path / "evidence.sqlite"
    cache = Cache(path)
    archive = Archive("http://unused.invalid", cache)

    def block(number):
        return Block(number, str(number), number * 12)

    def request(method, params):
        assert method == "eth_getCode"
        return "0x6000" if int(params[1]["blockHash"]) >= 123 else "0x"

    monkeypatch.setattr(archive, "block", block)
    monkeypatch.setattr(archive, "request", request)
    if known_later_deployment:
        assert archive.deployment("contract", block(500)) == block(123)
    with pytest.raises(Unavailable) as online:
        archive.deployment("contract", block(122))
    assert str(online.value) == "no contract at contract by block 122"
    cache.close()

    cache = Cache(path, offline=True)
    archive = Archive("http://unused.invalid", cache)

    def forbidden(*args):
        pytest.fail("offline deployment lookup contacted the RPC")

    monkeypatch.setattr(archive, "request", forbidden)
    with pytest.raises(Unavailable) as offline:
        archive.deployment("contract", block(122))
    assert str(offline.value) == str(online.value)
    cache.close()


@pytest.mark.parametrize(
    "raw,expected",
    [
        ({"transactions": [{"gasPrice": "0x5"}, {"gasPrice": "0x8"}]}, 7),
        (
            {
                "baseFeePerGas": "0x64",
                "transactions": [
                    {"maxFeePerGas": "0x66", "maxPriorityFeePerGas": "0xa"},
                    {"gasPrice": "0x68"},
                    {"maxFeePerGas": "0xc8", "maxPriorityFeePerGas": "0x4"},
                ],
            },
            104,
        ),
    ],
)
def test_gas_price_uses_historical_effective_median(
    tmp_path, monkeypatch, raw, expected
):
    cache = Cache(tmp_path / "evidence.sqlite")
    archive = Archive("http://unused.invalid", cache)
    monkeypatch.setattr(archive, "rpc", lambda method, params, block_hash=None: raw)
    assert archive.gas_price(Block(1, "hash", 1)) == expected
    cache.close()
