# HODL or Not, Here We Come

Compare historical Ethereum positions that start with the same USD value of
USDC, WBTC, native ETH, or CRV. The Python CLI models one deposit, monthly
Curve gauge compounding, and withdrawal into the starting asset.

These are historical estimates. The added position does not change later
market activity. See [validation and sample reports](docs/verification.md) for
the fixed-block mainnet checks, assumptions, and reproducible results.

## Setup

Install Python 3.12 or later, [uv](https://docs.astral.sh/uv/getting-started/installation/),
and [Foundry](https://getfoundry.sh/introduction/installation/) with `anvil` on
your PATH. Then install the locked dependencies:

```bash
uv sync --locked
cp .env.example .env
```

Set `HODL_RPC_URL` in `.env` to your Ethereum mainnet archive endpoint. The CLI
and mainnet tests read `.env` from the current directory. Git ignores this
file. An existing environment variable takes priority over `.env`, and
`--rpc-url` takes priority over both. You do not need to export the URL for
each command.

The RPC must provide historical state, blocks, and transaction data, including
hash-pinned `eth_call`, `eth_getCode`, and `eth_getStorageAt` reads. The tool
checks chain ID 1. It requires no wallet or private key. All transaction
execution occurs on a temporary Anvil fork bound to `127.0.0.1`. The archive
bridge accepts read methods only. The tool does not submit mainnet transactions.

`pyproject.toml` and `uv.lock` define the active CLI and its dependencies. The
old Brownie files in `src/`, `scripts/`, and `requirements.txt` contain unfinished
Uniswap work. They are not part of the CLI package or its validation checks.

## Compare

```bash
uv run hodl compare \
  --start 2022-01-01 \
  --end 2023-01-01 \
  --assets USD,BTC,ETH,CRV \
  --usd-value 10000 \
  --csv reports/2022.csv
```

`--start` is required. The end defaults to the latest finalized block. The
starting value defaults to $10,000 for each asset. Observations occur on monthly
anniversaries. A date means midnight UTC. A timestamp must include its timezone.
Month-end dates retain the original day where possible: January 31 becomes
February 28 or 29, then March 31. The final date always appears.

The mappings are **USD → USDC**, **BTC → WBTC**, **ETH → native ETH**, and
**CRV → CRV**. The report prints full token addresses and decimals. WETH wrapping
and unwrapping incur gas. USDC and WBTC use their actual historical token prices.
The initial assets are already held. Each scenario pays later conversion costs.

Filter strategies with repeated `--strategy` arguments:

```bash
uv run hodl compare --start 2022-01-01 --end 2023-01-01 \
  --strategy curve-tricrypto2-lp --strategy yearn-usdc-v2
uv run hodl list
```

The fixed catalog contains four Curve pools, each with LP and gauge positions,
and six Yearn vaults. It retains retired contracts. `hodl list` prints full
contract and LP addresses, versions, deployment blocks, and dates verified from
archive state. Without RPC configuration, it prints unverified dates and returns
status 2. The factory gauge for CRV/cvxCRV v2 resolves from historical factory
state once at entry. A run never changes its selected gauge.

## Results and costs

The final and monthly tables show starting quantity, ending quantity, ending
USD value, net return, estimated gas costs, and gain or loss against holding
the starting asset. Separate USDC, WBTC, ETH, CRV, and constant USD cash benchmarks
remain in the report even when `--assets` selects fewer starting assets.

Each monthly value estimates an exit from the retained shares. It does not
reopen the position. Entry costs occur once. Monthly gauge compounding claims
and sells rewards, deducts costs, buys LP tokens, and stakes the new LP tokens.
If rewards cannot cover costs, the position retains them until the next attempt.
Missing compounding data makes later results incomplete. The final exit sells
remaining rewards without a deposit immediately before withdrawal.

Conversions search direct routes and routes through WETH, USDC, USDT, or WBTC,
with no more than two swaps. They cover the catalog Curve pools and Uniswap V3
fee tiers 100, 500, 3000, and 10000. The selected route maximizes output value
after measured gas among supported candidates. Exact fork execution includes
swap fees and price impact. This is not a search across all exchanges. A pool
uses the starting coin when supported; otherwise it uses its supported
USDC, USDT, ETH, or CRV entry coin.

The engine uses deployed Yearn deposit and redemption methods. V2 `0.3.5`
issues shares against total assets; later supported V2 versions issue shares
against unlocked assets. Redemption accounts for locked profit. V3 uses its
preview, conversion, and limit methods. The tool does not add yield or deduct
fees already included in share value. V2 exits allow the deployed default of
one basis point of withdrawal loss. V3 uses its deployed `redeem` defaults.

Curve gauge accounting uses cumulative historical integrals. Local boundary
checkpoints include accrued CRV and extra rewards. CRV uses an unboosted working
balance of 40% of LP balance. Removed reward tokens that the adapter cannot
claim remain visible as unsupported results.

Gas units come from local receipts for approvals, wrapping, swaps, deposits,
staking, claims, and withdrawals. The fork uses the historical EVM rules. The
price is base fee plus the median effective priority fee from the selected
block, or median transaction gas price before London. Half-wei medians round
up. Gas funding debits equivalent asset value at historical prices. This is a
funding estimate, not a separate quoted gas-purchase transaction.

Unavailable entries, missing prices, unsupported rewards, and blocked or
unaffordable exits remain visible. Empty result fields do not mean zero return.
An accounting value, when available, is separate from withdrawal proceeds. The
tool does not rank incomplete values as complete net outcomes.

## Evidence and repeatability

The default SQLite cache is `.hodl/history.sqlite`. It stores blocks, calls,
logs, prices, fork reads, and action results with source details and block
hashes. It stores a hash of the RPC URL, not the provider credential. Fork
receipts preserve action arguments, full contract addresses, and gas units.
Action evidence includes the calculation-code fingerprint, decimal precision,
rounding mode, and Anvil/library versions. Display and configuration-file
changes do not invalidate action results; resolved inputs identify each action.
It also retains unavailable action outcomes. Use a new `--cache` path to
reassess a failed action after the data source changes.

DefiLlama price selection accepts only points at or before the block timestamp
and no more than 24 hours old. It never substitutes a current price. CSV contains
the same monthly observations as the text report. Its adjacent JSON file records
scenario inputs, block hashes, contracts, assumptions, and dated actions.

Use an explicit end date for an offline rerun. Keep the same RPC URL as the
cache source identifier; offline mode makes no remote requests:

```bash
uv run hodl compare --start 2022-01-01 --end 2023-01-01 \
  --csv reports/2022-cached.csv --offline
```

Exit status 0 means all rows are complete. Status 1 means the report contains
unavailable or incomplete results. Status 2 means a setup or input error.

## Development

```bash
uv run ruff format --check hodl tests
uv run ruff check hodl tests
uv run ty check
uv run pytest -m 'not fork'
uv run pytest -m fork
```

Use `uv lock --upgrade` and `uv sync --locked` to refresh compatible dependencies.
Direct runtime and development dependencies are pinned in `pyproject.toml`.
Review those pins when newer direct releases become available.

Contract references: [Yearn V2](https://github.com/yearn/yearn-vaults/tree/v0.4.3/contracts),
[Yearn V3](https://docs.yearn.fi/developers/smart-contracts/V3/VaultV3),
[Curve gauges](https://github.com/curvefi/curve-dao-contracts/tree/master/contracts/gauges),
[Curve pool metadata](https://github.com/curvefi/curve-js/blob/master/src/constants/pools/ethereum.ts),
[DefiLlama API](https://api-docs.defillama.com/llms-free.txt), and
[mainnet fork schedule](https://github.com/ethereum/go-ethereum/blob/master/params/config.go).
