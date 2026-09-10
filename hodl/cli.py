"""CLI process setup; importing the package does not contact any service."""

import argparse
import os
import sys
from dataclasses import asdict
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path

from hodl.cache import Cache
from hodl.catalog import strategies, verify
from hodl.data import Archive, Prices
from hodl.engine import compare
from hodl.model import Block, Scenario, Unavailable, parse_date
from hodl.report import export_csv, render
from hodl.simulation import Simulator


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="hodl",
        description="Compare historical Ethereum positions after estimated costs.",
    )
    commands = root.add_subparsers(dest="command", required=True)
    listing = commands.add_parser(
        "list", help="show the fixed strategy catalog and verified deployment dates"
    )
    comparison = commands.add_parser(
        "compare", help="compare one initial position per starting asset and strategy"
    )
    for command in (listing, comparison):
        command.add_argument(
            "--rpc-url",
            default=os.environ.get("HODL_RPC_URL"),
            help="archive RPC (default: HODL_RPC_URL)",
        )
        command.add_argument("--cache", type=Path, default=Path(".hodl/history.sqlite"))
        command.add_argument(
            "--offline",
            action="store_true",
            help="use cached evidence only; compare needs --end",
        )
    comparison.add_argument(
        "--start", required=True, help="YYYY-MM-DD or ISO timestamp with timezone"
    )
    comparison.add_argument("--end", help="default: latest finalized block")
    comparison.add_argument("--assets", default="USD,BTC,ETH,CRV")
    comparison.add_argument("--usd-value", default="10000")
    comparison.add_argument(
        "--strategy",
        action="append",
        help="fixed strategy name; repeat to select multiple",
    )
    comparison.add_argument(
        "--csv",
        type=Path,
        help="export all monthly rows plus a JSON action/source manifest",
    )
    return root


def run(args: argparse.Namespace) -> int:
    selected = strategies()
    if args.command == "compare" and args.strategy:
        names = {strategy.name for strategy in selected}
        unknown = set(args.strategy) - names
        if unknown:
            raise ValueError("unknown strategy: " + ", ".join(sorted(unknown)))
        selected = tuple(
            strategy for strategy in selected if strategy.name in args.strategy
        )
    if not args.rpc_url:
        if args.command == "list":
            for strategy in selected:
                pool = strategy.pool
                gauge = strategy.gauge or (
                    "historical factory lookup" if strategy.kind == "gauge" else "-"
                )
                print(
                    f"{strategy.name}: {strategy.address} version={strategy.version} "
                    f"LP={pool.lp.address if pool else '-'} "
                    f"gauge={gauge} "
                    "supported dates=unverified (set HODL_RPC_URL)"
                )
            return 2
        raise ValueError("set HODL_RPC_URL to an Ethereum mainnet archive endpoint")
    cache = Cache(args.cache, offline=args.offline)
    archive = Archive(args.rpc_url, cache)
    try:
        if not args.offline:
            archive.check_mainnet()
        if args.command == "list":
            raw = cache.get(
                "catalog-ceiling-v1",
                [],
                archive.source,
                lambda: asdict(archive.finalized()),
            )
            ceiling = Block(**raw)
            failures = 0
            for strategy in selected:
                try:
                    record = verify(archive, strategy, ceiling)
                    available = max(
                        record.deployment.timestamp,
                        record.gauge_deployment.timestamp
                        if record.gauge_deployment
                        else 0,
                    )
                    gauge_deployment = (
                        record.gauge_deployment.number
                        if record.gauge_deployment
                        else "-"
                    )
                    print(
                        f"{strategy.name}: {strategy.address} "
                        f"version={strategy.version} "
                        f"deployment={record.deployment.number} "
                        f"{record.deployment.date} "
                        f"LP={strategy.pool.lp.address if strategy.pool else '-'} "
                        f"gauge={record.gauge or '-'} "
                        f"gauge_deployment={gauge_deployment} "
                        f"supported_from_timestamp={available}; "
                        "historical entry and exit limits apply"
                    )
                except Unavailable as exc:
                    failures += 1
                    print(
                        f"{strategy.name}: {strategy.address} "
                        f"supported dates=unavailable: {exc}"
                    )
            return 1 if failures else 0
        start = parse_date(args.start)
        if args.end:
            end = parse_date(args.end)

            def finalized_ceiling() -> dict:
                finalized = archive.finalized()
                if end > finalized.timestamp:
                    raise ValueError("end is after the latest finalized block")
                return asdict(finalized)

            ceiling = Block(
                **cache.get("run-ceiling-v1", end, archive.source, finalized_ceiling)
            )
        else:
            ceiling = archive.finalized()
            end = ceiling.timestamp
        scenario = Scenario(
            start, end, tuple(args.assets.split(",")), Decimal(args.usd_value)
        )
        prices = Prices(cache)
        result = compare(
            scenario, selected, archive, prices, Simulator(archive, prices), ceiling
        )
        print(render(result), end="")
        if args.csv:
            export_csv(result, args.csv)
        return 1 if any(row.status != "complete" for row in result.observations) else 0
    finally:
        cache.close()


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        with localcontext() as context:
            context.prec = 100
            return run(args)
    except (ValueError, InvalidOperation, Unavailable, OSError) as exc:
        print(f"hodl: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
