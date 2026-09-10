"""Read project settings at startup without changing process environment state."""

import os
from pathlib import Path

from dotenv import dotenv_values


def rpc_url() -> str | None:
    if "HODL_RPC_URL" in os.environ:
        return os.environ["HODL_RPC_URL"]
    return dotenv_values(Path.cwd() / ".env").get("HODL_RPC_URL")
