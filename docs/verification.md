# Verification status

All **103 tests have passed**: 80 local tests and 23 fixed-block mainnet tests.
The latest full run passed 101 tests. Archive RPC transport failures prevented
Anvil startup in the ETH/stETH and CRV/cvxCRV v2 repeated-claim checks. Both
checks passed on a focused host rerun. Ruff formatting, Ruff checks, ty, and
wheel/source builds pass. The unfinished Brownie files also pass a Python
syntax check; they remain outside the active CLI package and runtime tests.

Price-response regressions cover timeouts, connection resets, and incomplete
HTTP reads. Failed reads remain retryable. The CLI keeps unavailable rows in
text and CSV output and returns status 1 after a price timeout.

The four gauge regressions previously passed using saved mainnet state with
`Cache(offline=True)` and remote RPC requests disabled.

The V3 regression tests first failed on the old implementation. They cover an
unspent unit in either hop, rollback of the whole candidate, and selection of an
alternative route that spends the full input. The guard checks source-token
balance changes because the deployed
[Uniswap router](https://github.com/Uniswap/v3-periphery/blob/main/contracts/SwapRouter.sol)
returns output without requiring that all requested input was spent.

Gauge checks restore a real prior claim, verify that the same boundary pays no
rewards twice, and compare later rewards and receipt gas against reset counters.
All four versions return identical rewards in the two gas-control cases. Resetting
`integrate_fraction` and `MINTER.minted` adds exactly **34,200 gas** to the CRV
claim. The saved state follows the
[Curve minter accounting](https://github.com/curvefi/curve-dao-contracts/blob/master/contracts/Minter.vy).

| Gauge | Later claim block | Restored-counter gas | Reset-counter gas |
|---|---:|---:|---:|
| 3pool | 14297758 | 352235 | 386435 |
| tricrypto2 | 14297758 | 352337 | 386537 |
| ETH/stETH | 14297758 | 352525 | 386725 |
| CRV/cvxCRV v2 | 19422438 | 389023 | 423223 |

The first three checks use blocks 13916165, 14116761, and 14297758. The factory
gauge check uses 18994253, 19215377, and 19422438. Their hashes are recorded in
the [2022 Q1](samples/2022-q1.json) and [2024 CRV](samples/2024-crv-gauge-compound.json)
sample manifests and CSV observations. Local tests also verify packed reward
storage, claim-state cache serialization, capture before snapshot rollback, and
state persistence across skipped compounds and hypothetical exits.

The offline checks exposed an Anvil receipt race. The harness now mines each
local transaction before reading its receipt, so it does not request an unmined
local transaction's receipt from the archive. Timestamp, gas, and snapshot checks
pass with this mining sequence.

These fixes change the calculation fingerprint, so earlier action results
require regeneration; they cannot supply current net rankings.

The ETH/stETH vault previously passed its fixed-block mainnet check. Its contract is
`0xdCD90C7f6324cfa40d7169ef80b12031770B4325`, version `0.3.0`, with underlying
`0x06325440D014e39736583c165C2963BA99fAf14E`. It deployed at block 11,654,862
(`0x0d39d66f9dcc21aafaa722e18cf6477394013d64ea48b22d4b94e61888c48c2b`).
The mainnet check at block 14,000,000 verified issuance, redemption, receipt gas,
and the deployment boundary. The adapter follows the
[deployed version's rules](https://github.com/yearn/yearn-vaults/blob/v0.3.0/contracts/Vault.vy)
for total-asset share accounting without locked profit. Harvests and fees remain
in the share value; the calculation does not add or subtract them again.

The supplied archive node recovered after an earlier connection outage. The full
mainnet test set now passes, including the ETH/stETH vault. Reporting tests cover
equal initial USD values, a winner across starting assets, USD gaps against both
benchmarks, holding and cash winners, date boundaries, incomplete results, and
missing plain-asset vaults. The plain vault matches the starting asset; the
overall winner uses the highest complete USD proceeds across the comparison.

The original samples at the end of this document record commit `567e7c4`, before the
ETH/stETH vault and benchmark columns were added. Their manifests
retain the calculation fingerprint. Use that commit for byte-exact replay of
those files, or regenerate them with the current code and catalog.

## Reports with the review fixes

The [updated four-asset report](samples/2022-q1-reviewed.txt) uses the corrected
swap and claim accounting, all fifteen strategies, and $10,000 per starting
asset from 2022-01-01 through 2022-04-01. All eleven deployed strategies complete
their forty-four positions. The 195 monthly rows contain 147 complete outcomes
and 48 unavailable entries for contracts that had not deployed. The report
records 44 entries, 44 exits, and 24 compound attempts that retain rewards because
gas costs exceed proceeds. It has no missing-data or blocked-exit rows.

The overall USD winner is Yearn USDC V2 funded with USDC: **$10,062.32**, or
**+0.6232%** after costs. Its estimated gas is $61.56; it beats holding USDC by
only $0.38. The ETH-funded pool and vault comparison is:

| Position | Ending ETH | Ending USD | Gas USD | USD gap against plain WETH vault |
|---|---:|---:|---:|---:|
| Hold ETH | 2.70720955 | 8888.59 | 0.00 | +36.33 |
| Curve ETH/stETH LP | 2.71108215 | 8901.30 | 62.30 | +49.05 |
| Curve ETH/stETH gauge | 2.61043409 | 8570.85 | 482.11 | -281.41 |
| Yearn WETH V2 | 2.69614410 | 8852.26 | 69.40 | 0.00 |
| Yearn ETH/stETH V2 | 2.66605253 | 8753.46 | 251.39 | -98.80 |

These figures round for readability. The [CSV](samples/2022-q1-reviewed.csv)
retains full precision and gaps against the overall winner. The ETH/stETH Yearn
vault includes harvests and fees through share value. In this period, it trails
the plain WETH vault after costs. Its estimated gas alone is $181.99 higher.

```bash
uv run hodl compare --start 2022-01-01 --end 2022-04-01 \
  --assets USD,BTC,ETH,CRV --usd-value 10000 --cache .hodl/review-fixes.sqlite \
  --csv docs/samples/2022-q1-reviewed.csv
```

Status 1 is expected for the undeployed contracts. With RPC and HTTP request
functions disabled, the offline rerun returns the same status and produces
byte-identical text, CSV, and JSON files.

The [updated $1,000,000 CRV gauge example](samples/2024-crv-gauge-compound-reviewed.txt)
also completes and replays offline with identical text, CSV, and JSON files.
It covers 2024-01-13 through 2024-03-13 and executes one monthly compound. That
compound uses 818,332 gas, estimated at $120.45. Total estimated gas is $258.80.
The position ends at $1,422,021.23, versus $1,523,202.62 for holding CRV.
The cached compound records cumulative CRV entitlement and minted counters of
`13812903520462069203270`. Both the hypothetical exit and the final exit restore
that exact saved account state. The run returns status 0.

```bash
uv run hodl compare --start 2024-01-13 --end 2024-03-13 --assets CRV \
  --usd-value 1000000 --strategy curve-crv-cvxcrv-v2-gauge \
  --cache .hodl/crv-reviewed.sqlite \
  --csv docs/samples/2024-crv-gauge-compound-reviewed.csv
```

## Original release validation

All **80 tests passed**, including all 18 fixed-block mainnet tests. Validation
used the owner's Ethereum archive node. Ruff formatting, Ruff checks, and ty
checks pass. The local Anvil harness verifies gas rules before and after
EIP-1559, fixed timestamps, snapshots, concurrent archive reads, and rejection
of archive write methods. Wheel and source-distribution builds pass.

The mainnet checks cover deposits, redemptions, and receipt gas for all fourteen
strategies. Four independent checks compare historical gauge integrals with
actual CRV and extra-token claims. Each contract check verifies the deployment
block and the preceding block without code.

| Contract group | Fixed block | UTC | Block hash |
|---|---:|---|---|
| 3pool, tricrypto2, ETH/stETH, and their selected V2 vaults | 14000000 | 2022-01-13T22:59:55Z | `0x9bff49171de27924fa958faf7b7ce605c1ff0fdee86f4c0c74239e6ae20d9446` |
| CRV/cvxCRV v2 pool, gauge, and vault | 19000000 | 2024-01-13T19:17:23Z | `0xcf384012b91b081230cdf17a3f7dd370d8e67056058af6b272b3d54aa2714fac` |
| Yearn USD V3 | 24400000 | 2026-02-06T19:54:35Z | `0xe75db0b5a5e6602a67424c7895e5ca0026028df628a8261dd796bbfab7113fce` |

Each gauge test compares its group block with the block 10,000 blocks later.
The [verified catalog](samples/catalog.txt) records all deployment blocks,
versions, LP addresses, and gauges. Yearn USD V3 deployed at block 24,271,831.

Mainnet checks found and corrected three adapter errors. Stable-pool LP links
use Curve's historical registry. Getter traces locate factory-gauge mappings
beyond the large fixed-size arrays. V3 withdrawal checks compare assets with
`maxWithdraw` under the deployed redemption loss policy, since `maxRedeem`
can round a valid full exit down by one share.

Regression tests cover the Yearn share-price error, 6/8/18-decimal amounts,
locked profit, calendar dates, historical block and price selection, cache
identity, gas prices, persistent shares, entry costs, and monthly compounding.
The review fixes preserve tiny rewards, measure gas before rejecting a deposit
near its capacity limit, and cache the finalized end for offline replay.
Absent-contract checks run before the deployment lookup so offline reports
retain the same reason, including when a later deployment is already cached.

A live DefiLlama check for 2022-01-01 returned a USDC observation 11 seconds
after the target. The selection rule rejected it. The chart request selected
prior USDC and WBTC observations within 24 hours.

The dependency refresh uses web3.py 8.0.0, eth-abi 6.0.0, pytest 9.1.1,
Ruff 0.16.6, ty 0.0.80, python-dotenv 1.2.3, and hatchling 1.32.0.
`uv lock --upgrade` selected the latest compatible transitive releases on
2026-09-10. `pip-audit` found no known vulnerabilities in the exported lockfile.
Pydantic pins pydantic-core
2.46.5. eth-abi constrains parsimonious to 0.10.x. No dependency override bypasses
these upstream requirements.

## Original sample reports

The [Yearn V3 sample](samples/yearn-v3-latest.txt) starts on 2026-08-01 with
$10,000 of USDC. Its end is 2026-09-10T09:07:35Z, first selected by a command
without `--end`. The command below pins that time for reproduction. The report
also includes all four holding benchmarks and constant USD cash. The command
reads the saved endpoint from the ignored `.env` file:

```bash
uv run hodl compare --start 2026-08-01 --assets USD \
  --end 2026-09-10T09:07:35Z \
  --strategy yearn-usd-v3 --cache .hodl/default-end.sqlite \
  --csv docs/samples/yearn-v3-latest.csv
```

An offline run using the printed end timestamp returns status 0. Its text,
CSV, and JSON files are byte-identical to the online result. The replay check
replaces both RPC and HTTP request functions with failures to prove that no
network requests occur.

The CRV/cvxCRV v2 gauge samples cover 2024-01-13 through 2024-03-13. The
[$10,000 sample](samples/2024-crv-gauge.txt) retains rewards at the monthly
attempt because proceeds cannot cover gas. The
[$1,000,000 sample](samples/2024-crv-gauge-compound.txt) completes the monthly
claim and reinvestment. That action uses 835,432 gas units, estimated at
$122.96668068311424919264 at the action block. These are hypothetical positions;
the larger amount tests the successful compounding path.

Both gauge samples return status 0 and replay offline with identical text,
CSV, and JSON files. The sidecar JSON files record the starting value and all
actions. Regenerate them with:

```bash
uv run hodl compare --start 2024-01-13 --end 2024-03-13 --assets CRV \
  --strategy curve-crv-cvxcrv-v2-gauge --cache .hodl/crv-gauge.sqlite \
  --csv docs/samples/2024-crv-gauge.csv
uv run hodl compare --start 2024-01-13 --end 2024-03-13 --assets CRV \
  --usd-value 1000000 --strategy curve-crv-cvxcrv-v2-gauge \
  --cache .hodl/crv-gauge.sqlite --csv docs/samples/2024-crv-gauge-compound.csv
```

The [full four-asset comparison](samples/2022-q1.txt) covers 2022-01-01 through
2022-04-01, from block 13,916,165 to block 14,497,033. Its completed run has 183
monthly rows: 135 complete results and 48 unavailable entries. Curve CRV/cvxCRV
v2, its Yearn vault, and Yearn USD V3 had not deployed at entry. Both Curve LP
and gauge positions therefore remain unavailable for that pool.

The ten deployed strategies complete all forty starting positions. The report
records forty entries, forty final exits, and twenty-four compounding attempts
that retain rewards because gas costs exceed the proceeds.

```bash
uv run hodl compare --start 2022-01-01 --end 2022-04-01 \
  --assets USD,BTC,ETH,CRV --usd-value 10000 --cache .hodl/2022-q1.sqlite \
  --csv docs/samples/2022-q1.csv
```

Status 1 is expected for this period because the report retains the undeployed
contracts. All 183 rows match the earlier completed run. An offline replay with
RPC and HTTP calls disabled returns status 1 and produces byte-identical text,
CSV, and JSON files, including the unavailable-contract explanations.
