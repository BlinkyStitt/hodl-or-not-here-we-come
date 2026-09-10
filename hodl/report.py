"""Text and CSV render the same accounting records."""

import csv
import json
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from hodl.catalog import assets
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


def table(rows: list[Observation]) -> str:
    fields = (
        "Strategy",
        "Asset",
        "Status",
        "Start quantity",
        "End quantity",
        "End USD",
        "Net %",
        "vs hold USD",
        "Gas USD",
        "Accounting USD",
    )
    records = [fields]
    for row in rows:
        records.append(
            tuple(
                scalar(value)
                for value in (
                    row.strategy,
                    row.asset,
                    row.status,
                    row.start_quantity,
                    row.end_quantity,
                    row.end_usd,
                    row.net_return * 100 if row.net_return is not None else None,
                    row.versus_hold_usd,
                    row.gas_usd,
                    row.accounting_usd,
                )
            )
        )
    widths = [
        max(len(record[index]) for record in records) for index in range(len(fields))
    ]
    output = [
        " | ".join(
            value.ljust(width) for value, width in zip(record, widths, strict=True)
        )
        for record in records
    ]
    for row in rows:
        if row.note:
            output.append(f"  {row.strategy}/{row.asset}: {row.note}")
        if row.route:
            output.append(
                f"  {row.strategy}/{row.asset} exit route: " + "; ".join(row.route)
            )
    return "\n".join(output)


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
    records = [row_record(row) for row in report.observations]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
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
