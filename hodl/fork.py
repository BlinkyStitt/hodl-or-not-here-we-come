"""Execute hypothetical actions on a private, disposable Anvil fork only."""

import json
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from eth_abi import decode, encode
from web3 import HTTPProvider, Web3

from hodl.catalog import ETH, WETH
from hodl.data import Archive, calldata
from hodl.model import Block, Reverted, Token, Unavailable

ACCOUNT = "0xcFc14D4f06071DEA75D35489014F389a1C20e0C7"


def historical_hardfork(block: Block) -> str:
    """Mainnet EVM schedule from go-ethereum/params/config.go."""
    for timestamp, name in (
        (1764798551, "osaka"),
        (1746612311, "prague"),
        (1710338135, "cancun"),
        (1681338455, "shanghai"),
    ):
        if block.timestamp >= timestamp:
            return name
    for number, name in (
        (15537394, "paris"),
        (12965000, "london"),
        (12244000, "berlin"),
        (9069000, "istanbul"),
        (7280000, "petersburg"),
        (4370000, "byzantium"),
        (2675000, "spuriousdragon"),
        (2463000, "tangerine"),
        (1150000, "homestead"),
    ):
        if block.number >= number:
            return name
    return "frontier"


class ReadBridge:
    """Cache Anvil's archive reads in SQLite and reject every remote mutation."""

    def __init__(self, archive: Archive, block: Block):
        self.archive = archive
        self.block = block
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                pass

            def do_POST(self) -> None:
                request = json.loads(
                    self.rfile.read(int(self.headers["Content-Length"]))
                )
                response = bridge.respond(request)
                body = json.dumps(response).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def respond(self, request: Any) -> Any:
        if isinstance(request, list):
            return [self.respond(item) for item in request]
        response = {"jsonrpc": "2.0", "id": request.get("id")}
        try:
            method, params = request["method"], request.get("params", [])
            params = [
                hex(self.block.number)
                if isinstance(param, str)
                and param in ("latest", "pending", "safe", "finalized")
                else param
                for param in params
            ]
            if method == "eth_chainId":
                result = "0x1"
            elif method == "eth_blockNumber":
                result = hex(self.block.number)
            elif method in {
                "eth_getBlockByNumber",
                "eth_getBlockByHash",
                "eth_getCode",
                "eth_getStorageAt",
                "eth_getBalance",
                "eth_getTransactionCount",
                "eth_getTransactionByHash",
                "eth_getTransactionReceipt",
                "eth_call",
                "eth_getLogs",
                "eth_getProof",
                "eth_getBlockReceipts",
            }:
                result = self.archive.rpc(method, params, self.block.hash)
            else:
                raise Unavailable(f"read-only archive bridge rejects {method}")
            response["result"] = result
        except Exception as exc:
            response["error"] = {"code": -32000, "message": str(exc)}
        return response

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


class Fork:
    def __init__(self, archive: Archive, block: Block):
        self.archive = archive
        self.block = block
        self.gas_units = 0
        self.gas_limit = 15_000_000
        self.base_fee: int | None = None
        self.transactions: list[dict] = []
        self.slots: dict[tuple, int] = {}
        self.process: subprocess.Popen | None = None
        self.bridge: ReadBridge | None = None
        self.temp: tempfile.TemporaryDirectory | None = None
        self.provider: HTTPProvider | None = None

    def __enter__(self) -> "Fork":
        binary = shutil.which("anvil")
        if binary is None:
            raise Unavailable(
                "Anvil is required for historical execution and gas measurement"
            )
        self.bridge = ReadBridge(self.archive, self.block)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.temp = tempfile.TemporaryDirectory(prefix="hodl-fork-")
        log = Path(self.temp.name) / "anvil.log"
        self.provider = HTTPProvider(
            f"http://127.0.0.1:{port}",
            request_kwargs={"timeout": 90},
            exception_retry_configuration=None,
        )
        command = [
            binary,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--fork-url",
            self.bridge.url,
            "--fork-block-number",
            str(self.block.number),
            "--chain-id",
            "1",
            "--hardfork",
            historical_hardfork(self.block),
            "--no-storage-caching",
            "--retries",
            "0",
        ]
        try:
            with log.open("wb") as output:
                self.process = subprocess.Popen(command, stdout=output, stderr=output)
            deadline = time.monotonic() + 60
            while True:
                try:
                    latest = self.rpc("eth_getBlockByNumber", ["latest", False])
                    self.gas_limit = min(self.gas_limit, int(latest["gasLimit"], 16))
                    if "baseFeePerGas" in latest:
                        self.base_fee = int(latest["baseFeePerGas"], 16)
                    if latest["hash"].lower() != self.block.hash.lower():
                        raise Unavailable(
                            "fork hash does not match the selected historical block"
                        )
                    break
                except Unavailable:
                    if time.monotonic() >= deadline:
                        raise Unavailable(
                            "Anvil did not start: " + log.read_text()[-2000:]
                        ) from None
                    time.sleep(0.1)
            self.rpc("anvil_impersonateAccount", [ACCOUNT])
            self.rpc("anvil_setBalance", [ACCOUNT, hex(10**30)])
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self.process is not None:
            # This process belongs to this context; shutdown is normal resource cleanup.
            self.process.terminate()
            self.process.wait(timeout=15)
        if self.bridge is not None:
            self.bridge.close()
        if self.temp is not None:
            self.temp.cleanup()

    def rpc(self, method: str, params: list) -> Any:
        if self.provider is None:
            raise RuntimeError("fork context is not open")
        try:
            response = self.provider.make_request(method, params)
        except Exception as exc:
            raise Unavailable(f"local fork transport failed: {method}") from exc
        if "error" in response:
            if "execution reverted" in str(response["error"]).lower():
                raise Reverted(f"local fork {method}: {response['error']}")
            raise Unavailable(f"local fork {method}: {response['error']}")
        return response["result"]

    @contextmanager
    def snapshot(self) -> Iterator[None]:
        snapshot = self.rpc("evm_snapshot", [])
        gas, count = self.gas_units, len(self.transactions)
        try:
            yield
        finally:
            if not self.rpc("evm_revert", [snapshot]):
                raise RuntimeError("failed to restore the local fork snapshot")
            self.gas_units = gas
            del self.transactions[count:]

    def call(
        self,
        address: str,
        signature: str,
        types: tuple[str, ...] = (),
        args: tuple = (),
        returns: tuple[str, ...] = ("uint256",),
    ) -> Any:
        raw = self.rpc(
            "eth_call",
            [
                {
                    "to": address,
                    "from": ACCOUNT,
                    "data": calldata(signature, types, args),
                },
                "latest",
            ],
        )
        try:
            values = decode(returns, bytes.fromhex(raw.removeprefix("0x")))
        except Exception as exc:
            raise Unavailable(f"cannot decode {signature} on {address}") from exc
        return values[0] if len(values) == 1 else values

    def transact(
        self,
        address: str,
        signature: str,
        types: tuple[str, ...] = (),
        args: tuple = (),
        *,
        value: int = 0,
        label: str = "",
    ) -> None:
        # The fork's clock stays at the historical timestamp, including checkpoints.
        self.rpc("evm_setNextBlockTimestamp", [self.block.timestamp])
        if self.base_fee is not None:
            self.rpc("anvil_setNextBlockBaseFeePerGas", [hex(self.base_fee)])
        gas_price = self.archive.gas_price(self.block)
        tx = {
            "from": ACCOUNT,
            "to": address,
            "data": calldata(signature, types, args),
            "value": hex(value),
            "gas": hex(self.gas_limit),
            "gasPrice": hex(gas_price),
        }
        tx_hash = self.rpc("eth_sendTransaction", [tx])
        try:
            receipt = Web3(self.provider).eth.wait_for_transaction_receipt(
                tx_hash, timeout=60, poll_latency=0.05
            )
        except Exception as exc:
            raise Unavailable("local fork did not mine the action") from exc
        if receipt["status"] != 1:
            raise Reverted(
                f"{label or signature} reverted at block {self.block.number}"
            )
        raw_block = self.rpc(
            "eth_getBlockByNumber", [hex(receipt["blockNumber"]), False]
        )
        if int(raw_block["timestamp"], 16) != self.block.timestamp:
            raise Unavailable("fork changed the action timestamp")
        gas = receipt["gasUsed"]
        self.gas_units += gas
        self.transactions.append(
            {
                "contract": address,
                "signature": signature,
                "args": list(args),
                "gas_units": gas,
                "label": label,
                "value": value,
            }
        )

    def balance(self, token: Token) -> int:
        if token == ETH:
            return int(self.rpc("eth_getBalance", [ACCOUNT, "latest"]), 16)
        return self.call(token.address, "balanceOf(address)", ("address",), (ACCOUNT,))

    def approve(self, token: Token, spender: str, amount: int) -> None:
        if token == ETH:
            return
        allowance = self.call(
            token.address,
            "allowance(address,address)",
            ("address", "address"),
            (ACCOUNT, spender),
        )
        if allowance >= amount:
            return
        if allowance:
            self.transact(
                token.address,
                "approve(address,uint256)",
                ("address", "uint256"),
                (spender, 0),
                label="reset approval",
            )
        self.transact(
            token.address,
            "approve(address,uint256)",
            ("address", "uint256"),
            (spender, amount),
            label="approval",
        )

    def seed(self, token: Token, amount: int) -> None:
        """Assign the hypothetical owner's balance; keep market totals unchanged."""
        if token == ETH:
            self.rpc("anvil_setBalance", [ACCOUNT, hex(10**30 + amount)])
        else:
            self.set_mapping(token.address, "balanceOf(address)", (ACCOUNT,), amount)

    def set_mapping(
        self,
        address: str,
        getter: str,
        keys: tuple[str, ...],
        value: int,
        *,
        shift: int = 0,
    ) -> None:
        """Prove a storage slot with its getter; reject unsupported layouts."""
        cache_key = (address.lower(), getter, keys, shift)

        def read() -> int:
            return self.call(address, getter, ("address",) * len(keys), keys)

        def write(slot: int, raw: int) -> None:
            self.rpc(
                "anvil_setStorageAt",
                [address, hex(slot), "0x" + raw.to_bytes(32, "big").hex()],
            )

        if cache_key in self.slots:
            write(self.slots[cache_key], value << shift)
            if read() != value:
                raise Unavailable(f"storage layout changed for {address} {getter}")
            return
        probe = 2**71 + 19
        # Solidity and Vyper use opposite mapping key/slot order.
        for base in range(200):
            for solidity in (True, False):
                slot = base
                for key in keys:
                    types = (
                        ("address", "uint256") if solidity else ("uint256", "address")
                    )
                    values = (key, slot) if solidity else (slot, key)
                    slot = int.from_bytes(Web3.keccak(encode(types, values)), "big")
                old = self.rpc("eth_getStorageAt", [address, hex(slot), "latest"])
                write(slot, probe << shift)
                try:
                    matches = read() == probe
                except Unavailable:
                    matches = False
                finally:
                    self.rpc("anvil_setStorageAt", [address, hex(slot), old])
                if matches:
                    self.slots[cache_key] = slot
                    write(slot, value << shift)
                    if read() != value:
                        raise Unavailable(f"cannot seed {getter} exactly")
                    return
        raise Unavailable(f"unsupported storage layout: {address} {getter}")

    def wrap(self, amount: int) -> None:
        self.transact(WETH.address, "deposit()", value=amount, label="wrap ETH")

    def unwrap(self, amount: int) -> None:
        self.transact(
            WETH.address,
            "withdraw(uint256)",
            ("uint256",),
            (amount,),
            label="unwrap WETH",
        )
