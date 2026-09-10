from decimal import Decimal

import pytest

from hodl.cache import Cache
from hodl.data import Archive, last_block_at, select_price
from hodl.model import Block, Unavailable


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
