# Verification status

The ETH/stETH vault and USD benchmark changes have **72 passing local tests**.
The new vault also passed its fixed-block mainnet check. Its contract is
`0xdCD90C7f6324cfa40d7169ef80b12031770B4325`, version `0.3.0`, with underlying
`0x06325440D014e39736583c165C2963BA99fAf14E`. It deployed at block 11,654,862
(`0x0d39d66f9dcc21aafaa722e18cf6477394013d64ea48b22d4b94e61888c48c2b`).
The mainnet check at block 14,000,000 verified issuance, redemption, receipt gas,
and the deployment boundary. The adapter follows the
[deployed version's rules](https://github.com/yearn/yearn-vaults/blob/v0.3.0/contracts/Vault.vy)
for total-asset share accounting without locked profit. Harvests and fees remain
in the share value; the calculation does not add or subtract them again.

The later complete-suite attempt passed all 69 local tests, but all 19 mainnet
cases failed during setup because the configured RPC reset connections.
An independent curl check also returned `Connection reset by peer`. The new
ETH period report and its offline replay remain pending until RPC access returns.
Ruff formatting, Ruff checks, ty checks, and wheel/source builds pass for the
addition. The report correction also passes these checks. Reporting tests cover
equal initial USD values, a winner across starting assets, USD gaps against both
benchmarks, holding and cash winners, date boundaries, incomplete results, and
missing plain-asset vaults. The plain vault matches the starting asset; the
overall winner uses the highest complete USD proceeds across the comparison.

The reports below record the original release at commit `567e7c4`, before the
ETH/stETH vault and benchmark columns were added. Their manifests
retain the calculation fingerprint. Use that commit for byte-exact replay of
those files, or regenerate them with the current code and catalog.

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

## Sample reports

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
