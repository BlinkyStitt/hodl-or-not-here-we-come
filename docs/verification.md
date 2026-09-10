# Verification status

The mainnet release gate is **not complete**. This checkout and shell had no
configured archive RPC when implementation began. No historical comparison
report has been validated against mainnet state.

Current local validation: **46 passed, 18 skipped**. The 18 skips are the
mainnet fork tests. Ruff formatting, Ruff checks, and ty checks pass. The local
Anvil harness verifies gas receipts before and after EIP-1559, historical EVM
rules, fixed timestamps, snapshot restoration, and the archive bridge's
rejection of write methods. The source distribution and wheel build pass.

The local checks cover integer share accounting, 6/8/18-decimal assets, locked
profit, monthly dates, block selection, price age, stablecoin price changes,
cache source/hash separation, gas prices, retained shares, entry costs, monthly
compounding, skipped actions, missing-data rows, and CSV output.

A live DefiLlama check for 2022-01-01 returned a USDC observation 11 seconds
after the target. The selection rule rejected it. The chart request selected
prior USDC and WBTC observations within 24 hours.

The dependency refresh uses web3.py 8.0.0, eth-abi 6.0.0, pytest 9.1.1,
Ruff 0.16.6, ty 0.0.80, and hatchling 1.32.0. `uv lock --upgrade` selected
the latest compatible transitive releases on 2026-09-10. `pip-audit` found no
known vulnerabilities in the exported lockfile. Pydantic pins pydantic-core
2.46.5. eth-abi constrains parsimonious to 0.10.x. No dependency override bypasses
these upstream requirements.

Before release:

- Supply an Ethereum mainnet archive RPC as `HODL_RPC_URL`.
- Run the fixed-block tests for every catalog contract and gauge version.
- Verify deployment boundaries, LP links, the factory gauge, and extra rewards.
- Run all four starting assets against all fourteen strategies.
- Repeat the same comparison offline and compare CSV and JSON output.
- Commit a historical sample report with its dates, block hashes, assumptions,
  and unavailable rows. Do not label fixture output as historical results.

The old Brownie and unfinished Uniswap files remain outside the CLI package.
Their existing staged and unstaged changes must remain outside this task's
commit.
