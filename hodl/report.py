"""Text and CSV render the same accounting records."""

import csv
import json
from collections import defaultdict
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from operator import itemgetter
from pathlib import Path

from hodl.catalog import WETH, assets, strategies
from hodl.engine import Report
from hodl.model import Observation


def assumptions() -> tuple[str, ...]:
    return (
        (
            "Ethereum mainnet; timestamps use UTC and the last block at or "
            "before each time."
        ),
        (
            "Assets are already held at entry. USD=USDC, BTC=WBTC, ETH=native "
            "ETH, CRV=CRV."
        ),
        "Each starting asset has the same initial USD value; token amounts round down.",
        (
            "Historical prices must be at or before the block timestamp and at "
            "most 24 hours old."
        ),
        (
            "One entry; monthly observations are hypothetical exits. Only "
            "scheduled compounds change shares."
        ),
        (
            "Fixed vault and gauge; no migration. No veCRV boost. Final exit "
            "sells remaining rewards."
        ),
        (
            "The added position does not change later market activity, "
            "supplies, or reward integrals."
        ),
        "Routes cover the catalog Curve pools and Uniswap V3, with at most two swaps.",
        (
            "Swap execution includes fees and price impact; these are not "
            "exchange-wide best-route claims."
        ),
        (
            "Gas units come from local fork receipts, including approvals, "
            "wraps, swaps, and protocol actions."
        ),
        (
            "Gas funding debits equivalent asset value at historical prices; "
            "it is an estimate."
        ),
        (
            "Gas price uses the block's median priority fee plus base fee, or "
            "pre-London median gasPrice."
        ),
        (
            "An even-count median rounds up to the nearest wei. No current gas "
            "prices are substituted."
        ),
        (
            "Yearn V2 withdrawals use maxLoss=1 basis point. V3 uses the "
            "deployed redeem defaults."
        ),
        (
            "Yearn share value already includes reported fees and rewards. No "
            "extra yield is added."
        ),
        (
            "Unavailable or incomplete rows are not complete net outcomes; "
            "blank values do not mean zero."
        ),
        (
            "Best means the highest complete ending USD value across all selected "
            "positions, all asset holding benchmarks, and cash at that observation."
        ),
        (
            "The single-asset vault benchmark uses a selected vault whose "
            "underlying is the starting asset (WETH for ETH), without an LP."
        ),
        (
            "Both benchmark gaps use USD proceeds after costs from equal "
            "initial USD values."
        ),
        (
            "Benchmark winners are historical comparisons, not assumed "
            "migrations. Vault fees and harvests remain in share value."
        ),
    )


def scalar(value) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (tuple, list)):
        return json.dumps(value)
    return str(value)


def row_record(row: Observation) -> dict:
    return {
        "strategy": row.strategy,
        "asset": row.asset,
        "target_utc": datetime.fromtimestamp(row.target, UTC).isoformat(),
        "block": row.block.number,
        "block_hash": row.block.hash,
        "block_utc": row.block.date,
        "status": row.status,
        "start_quantity": row.start_quantity,
        "end_quantity": row.end_quantity,
        "end_usd": row.end_usd,
        "net_return_fraction": row.net_return,
        "versus_hold_usd": row.versus_hold_usd,
        "gas_usd": row.gas_usd,
        "accounting_usd": row.accounting_usd,
        "route": row.route,
        "note": row.note,
    }


def comparison_records(rows: list[Observation]) -> list[dict]:
    """Compare net USD proceeds by date, with a matching plain-asset vault."""
    groups: dict[tuple[str, int], list[Observation]] = defaultdict(list)
    outcomes: dict[int, list[tuple[str, str, Decimal]]] = defaultdict(list)
    for row in rows:
        groups[row.asset, row.target].append(row)
        if row.status == "complete" and row.end_usd is not None:
            outcomes[row.target].append((row.strategy, row.asset, row.end_usd))
    winners = {
        target: max(options, key=itemgetter(2)) for target, options in outcomes.items()
    }
    tokens = assets()
    catalog = strategies()
    benchmarks = {}
    for key, group in groups.items():
        token = WETH if key[0] == "ETH" else tokens.get(key[0])
        vault_names = {
            strategy.name
            for strategy in catalog
            if strategy.kind in ("v2", "v3")
            and strategy.pool is None
            and strategy.underlying == token
        }
        vault_options = [
            (row.strategy, row.end_usd)
            for row in group
            if row.status == "complete"
            and row.end_usd is not None
            and row.strategy in vault_names
        ]
        vault = max(vault_options, key=itemgetter(1), default=None)
        if vault:
            vault_status = "complete"
        elif not vault_names:
            vault_status = "not in catalog"
        elif any(row.strategy in vault_names for row in group):
            vault_status = "unavailable"
        else:
            vault_status = "not selected"
        benchmarks[key] = vault, vault_status
    records = []
    for row in rows:
        winner = winners.get(row.target)
        vault, vault_status = benchmarks[row.asset, row.target]
        quantity = row.end_quantity if row.status == "complete" else None
        end_usd = row.end_usd if row.status == "complete" else None
        records.append(
            {
                **row_record(row),
                "token_return_fraction": (
                    quantity / row.start_quantity - 1
                    if quantity is not None and row.start_quantity
                    else None
                ),
                "best_strategy": winner[0] if winner else None,
                "best_asset": winner[1] if winner else None,
                "versus_best_usd": (
                    end_usd - winner[2]
                    if end_usd is not None and winner is not None
                    else None
                ),
                "single_vault_strategy": vault[0] if vault else None,
                "single_vault_status": vault_status,
                "versus_single_vault_usd": (
                    end_usd - vault[1]
                    if end_usd is not None and vault is not None
                    else None
                ),
            }
        )
    return records


def asset_table(compared: list[dict]) -> str:
    first = compared[0]
    winner = (
        f"{first['best_strategy']}/{first['best_asset']}"
        if first["best_strategy"]
        else "unavailable"
    )
    lines = [
        f"{first['asset']}: gaps use net USD proceeds. "
        f"Best across the comparison: {winner}. "
        "Single-asset vault: "
        f"{first['single_vault_strategy'] or first['single_vault_status']}."
    ]
    fields = (
        "Strategy",
        "Status",
        "End USD",
        "Net USD %",
        "vs best USD",
        "vs vault USD",
        "vs hold USD",
        "Gas USD",
        "Start quantity",
        "End quantity",
        "Token %",
        "Accounting USD",
    )
    records = [fields]
    for row in compared:
        records.append(
            tuple(
                scalar(value)
                for value in (
                    row["strategy"],
                    row["status"],
                    row["end_usd"],
                    row["net_return_fraction"] * 100
                    if row["net_return_fraction"] is not None
                    else None,
                    row["versus_best_usd"],
                    row["versus_single_vault_usd"],
                    row["versus_hold_usd"],
                    row["gas_usd"],
                    row["start_quantity"],
                    row["end_quantity"],
                    row["token_return_fraction"] * 100
                    if row["token_return_fraction"] is not None
                    else None,
                    row["accounting_usd"],
                )
            )
        )
    widths = [
        max(len(record[index]) for record in records) for index in range(len(fields))
    ]
    output = [
        " | ".join(
            value.ljust(width) for value, width in zip(record, widths, strict=True)
        ).rstrip()
        for record in records
    ]
    for row in compared:
        if row["note"]:
            output.append(f"  {row['strategy']}/{row['asset']}: {row['note']}")
        if row["route"]:
            output.append(
                f"  {row['strategy']}/{row['asset']} exit route: "
                + "; ".join(row["route"])
            )
    return "\n".join([*lines, *output])


def table(rows: list[Observation]) -> str:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in comparison_records(rows):
        groups[row["asset"], row["target_utc"]].append(row)
    return "\n\n".join(asset_table(group) for group in groups.values())


def render(report: Report) -> str:
    lines = [
        "HODL or Not — historical estimate",
        f"Initial USD per asset: {report.scenario.usd_value}",
    ]
    for name, token in assets().items():
        lines.append(
            f"{name} = {token.symbol} ({token.address}); decimals={token.decimals}"
        )
    lines.extend(
        (
            f"Start block: {report.start_block.number} "
            f"{report.start_block.hash} {report.start_block.date}",
            f"End block: {report.end_block.number} "
            f"{report.end_block.hash} {report.end_block.date}",
        )
    )
    lines.extend(assumptions())
    lines.append("\nFinal comparison")
    lines.append(
        table([row for row in report.observations if row.target == report.scenario.end])
    )
    for target in sorted({row.target for row in report.observations}):
        lines.append(
            "\nMonthly values at " + datetime.fromtimestamp(target, UTC).isoformat()
        )
        lines.append(
            table([row for row in report.observations if row.target == target])
        )
    lines.append("\nDated actions")
    for key, events in report.actions.items():
        for event in events:
            lines.append(
                f"{key}: {event.block.date} block={event.block.number} {event.kind} "
                f"gas_units={event.gas_units} gas_wei={event.gas_wei} "
                f"gas_usd={event.gas_usd} "
                f"route={'; '.join(event.route)} {event.note}".rstrip()
            )
    return "\n".join(lines) + "\n"


def export_csv(report: Report, path: Path) -> None:
    records = comparison_records(report.observations)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=list(records[0]), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(
            {key: scalar(value) for key, value in row.items()} for row in records
        )
    metadata = {
        "engine": report.engine,
        "scenario": asdict(report.scenario),
        "start_block": asdict(report.start_block),
        "end_block": asdict(report.end_block),
        "assumptions": assumptions(),
        "assets": {k: asdict(v) for k, v in assets().items()},
        "contracts": report.contracts,
        "actions": {
            key: [asdict(event) for event in events]
            for key, events in report.actions.items()
        },
    }
    path.with_suffix(".json").write_text(
        json.dumps(metadata, indent=2, default=scalar) + "\n"
    )
