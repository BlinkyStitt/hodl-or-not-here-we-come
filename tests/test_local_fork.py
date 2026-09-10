"""Exercise Anvil lifecycle, timestamp pinning, and the read-only cache bridge."""

import shutil
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from web3 import HTTPProvider, Web3

from hodl.cache import Cache
from hodl.data import Archive
from hodl.fork import ACCOUNT, Fork, ReadBridge
from hodl.model import Block


def test_bridge_can_serve_a_read_while_another_read_is_waiting(tmp_path, monkeypatch):
    cache = Cache(tmp_path / "cache.sqlite")
    archive = Archive("http://unused.invalid", cache)
    entered, release = Event(), Event()

    def delayed(*args):
        entered.set()
        assert release.wait(5)
        return "0x0"

    monkeypatch.setattr(archive, "rpc", delayed)
    bridge = ReadBridge(archive, Block(1, "hash", 1))

    def request(method, params):
        return HTTPProvider(bridge.url).make_request(method, params)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            pending = executor.submit(request, "eth_getBalance", [ACCOUNT, "latest"])
            try:
                assert entered.wait(2)
                immediate = executor.submit(request, "eth_chainId", [])
                assert immediate.result(timeout=2)["result"] == "0x1"
            finally:
                release.set()
            assert pending.result(timeout=2)["result"] == "0x0"
    finally:
        release.set()
        bridge.close()
        cache.close()


@pytest.mark.skipif(shutil.which("anvil") is None, reason="Anvil is not installed")
@pytest.mark.parametrize(
    ("hardfork", "timestamp", "expected_gas"),
    [("frontier", 1640995200, 21272), ("shanghai", 1681338455, 21064)],
)
def test_local_fork_pins_clock_measures_gas_and_restores_snapshot(
    tmp_path, hardfork, timestamp, expected_gas
):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with (tmp_path / "upstream.log").open("wb") as log:
        process = subprocess.Popen(
            [
                "anvil",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--chain-id",
                "1",
                "--timestamp",
                str(timestamp),
                "--hardfork",
                hardfork,
            ],
            stdout=log,
            stderr=log,
        )
    cache = Cache(tmp_path / "history.sqlite")
    archive = Archive(f"http://127.0.0.1:{port}", cache)
    archive.provider = HTTPProvider(
        archive.url, request_kwargs={"timeout": 1}, exception_retry_configuration=None
    )

    def setup_rpc(method, params):
        response = archive.provider.make_request(method, params)
        assert "error" not in response, response
        return response.get("result")

    try:
        deadline = time.monotonic() + 10
        while True:
            try:
                archive.request("eth_chainId", [])
                break
            except Exception:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.1)
        setup_rpc("anvil_impersonateAccount", [ACCOUNT])
        setup_rpc("anvil_setBalance", [ACCOUNT, hex(10**25)])
        setup_rpc("evm_setNextBlockTimestamp", [timestamp + 1])
        tx_hash = setup_rpc(
            "eth_sendTransaction",
            [
                {
                    "from": ACCOUNT,
                    "to": "0x0000000000000000000000000000000000001234",
                    "value": "0x1",
                    "gas": hex(21000),
                    "gasPrice": hex(10**9),
                }
            ],
        )
        Web3(archive.provider).eth.wait_for_transaction_receipt(
            tx_hash, timeout=10, poll_latency=0.05
        )
        block = archive.block(1)
        assert block.timestamp == timestamp + 1
        with Fork(archive, block) as fork:
            assert fork.bridge is not None
            rejected = fork.bridge.respond(
                {"id": 1, "method": "eth_sendTransaction", "params": [{}]}
            )
            assert "read-only archive bridge rejects" in rejected["error"]["message"]
            with fork.snapshot():
                fork.transact(
                    "0x0000000000000000000000000000000000001234", "noop()", value=123
                )
                # Four nonzero selector bytes cost 68 each before Istanbul, 16 after.
                assert fork.gas_units == expected_gas
                assert fork.transactions[0]["signature"] == "noop()"
                assert (
                    int(
                        fork.rpc(
                            "eth_getBalance",
                            ["0x0000000000000000000000000000000000001234", "latest"],
                        ),
                        16,
                    )
                    == 124
                )
            assert fork.gas_units == 0
            assert fork.transactions == []
            assert (
                int(
                    fork.rpc(
                        "eth_getBalance",
                        ["0x0000000000000000000000000000000000001234", "latest"],
                    ),
                    16,
                )
                == 1
            )
            # A getter can expose only half of a packed storage word. Saving
            # and restoring the account must also preserve its hidden half.
            address = "0x0000000000000000000000000000000000001235"
            code = "0x6000546f" + "ff" * 16 + "1660005260206000f3"
            fork.rpc("anvil_setCode", [address, code])
            packed = (17 << 128) + 9
            fork.set_mapping(
                address, "claimed_reward(address)", (ACCOUNT,), packed, mask=2**128 - 1
            )
            assert (
                fork.call(address, "claimed_reward(address)", ("address",), (ACCOUNT,))
                == 9
            )
            assert (
                fork.mapping_word(address, "claimed_reward(address)", (ACCOUNT,))
                == packed
            )
        assert archive.request("eth_blockNumber", []) == "0x1"
        assert (
            cache.db.execute(
                "SELECT COUNT(*) FROM evidence WHERE block_hash=?", (block.hash,)
            ).fetchone()[0]
            > 0
        )
    finally:
        process.terminate()
        process.wait(timeout=10)
        cache.close()
