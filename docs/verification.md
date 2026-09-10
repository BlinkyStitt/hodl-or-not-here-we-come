# Verification status

All **77 tests pass**, including all 18 fixed-block mainnet tests. Validation
used the owner's Ethereum archive node. Ruff formatting, Ruff checks, and ty
checks pass. The local Anvil harness verifies gas rules before and after
EIP-1559, fixed timestamps, snapshots, concurrent archive reads, and rejection
of archive write methods. The wheel build passes.

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

A live DefiLlama check for 2022-01-01 returned a USDC observation 11 seconds
after the target. The selection rule rejected it. The chart request selected
prior USDC and WBTC observations within 24 hours.

The dependency refresh uses web3.py 8.0.0, eth-abi 6.0.0, pytest 9.1.1,
Ruff 0.16.6, ty 0.0.80, python-dotenv 1.2.3, and hatchling 1.32.0.
`uv lock --upgrade` selected the latest compatible transitive releases on
2026-09-10. `pip-audit` found no
known vulnerabilities in the exported lockfile. Pydantic pins pydantic-core
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

The full four-asset 2022 comparison is still being validated. Its sample and
cache replay evidence will be added after that run completes.
