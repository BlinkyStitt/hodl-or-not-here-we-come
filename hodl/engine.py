"""One entry, persistent shares, scheduled compounds, and hypothetical exits."""

from dataclasses import dataclass
from decimal import Decimal

from hodl.catalog import CRV, Strategy, assets, verify
from hodl.data import Archive, Prices
from hodl.model import (
    Action,
    Block,
    Observation,
    Position,
    Scenario,
    Unaffordable,
    Unavailable,
    anniversaries,
)
from hodl.positions import deposit_coin
from hodl.simulation import Simulator


@dataclass
class Report:
    scenario: Scenario
    start_block: Block
    end_block: Block
    observations: list[Observation]
    actions: dict[str, list[Action]]
    contracts: list[dict]
    engine: dict


def action(kind: str, target: int, block: Block, execution) -> Action:
    return Action(
        target,
        block,
        kind,
        execution.gas_units,
        execution.gas_wei,
        execution.gas_usd,
        execution.route,
    )


def compare(
    scenario: Scenario,
    selected: tuple[Strategy, ...],
    archive: Archive,
    prices: Prices,
    simulator: Simulator,
    ceiling: Block,
) -> Report:
    start = archive.at(scenario.start, ceiling)
    end = archive.at(scenario.end, ceiling)
    dates = anniversaries(scenario.start, scenario.end)
    blocks = {date: archive.at(date, ceiling) for date in dates}
    report = Report(scenario, start, end, [], {}, [], simulator.engine)
    tokens = assets()
    # Keep all four holding benchmarks when scenario assets are filtered.
    for name, token in tokens.items():
        initial = None
        initial_error = ""
        try:
            initial = token.units(
                scenario.usd_value / prices.at(token, start.timestamp).usd
            )
        except Unavailable as exc:
            initial_error = str(exc)
        for date in dates:
            block = blocks[date]
            try:
                if initial is None:
                    raise Unavailable(initial_error)
                quantity = token.quantity(initial)
                value = quantity * prices.at(token, block.timestamp).usd
                report.observations.append(
                    Observation(
                        "hold-" + name,
                        name,
                        date,
                        block,
                        "complete",
                        quantity,
                        quantity,
                        value,
                        value / scenario.usd_value - 1,
                        Decimal(0),
                        Decimal(0),
                        value,
                    )
                )
            except Unavailable as exc:
                report.observations.append(
                    Observation(
                        "hold-" + name, name, date, block, "unavailable", note=str(exc)
                    )
                )
    for date in dates:
        report.observations.append(
            Observation(
                "cash-USD",
                "cash",
                date,
                blocks[date],
                "complete",
                scenario.usd_value,
                scenario.usd_value,
                scenario.usd_value,
                Decimal(0),
                Decimal(0),
                Decimal(0),
                scenario.usd_value,
            )
        )

    for strategy in selected:
        verified = None
        entry_error = ""
        try:
            verified = verify(archive, strategy, start)
            report.contracts.append(
                {
                    "strategy": strategy.name,
                    "address": strategy.address,
                    "version": strategy.version,
                    "deployment": vars(verified.deployment),
                    "gauge": verified.gauge,
                    "gauge_deployment": vars(verified.gauge_deployment)
                    if verified.gauge_deployment
                    else None,
                    "code_hash": verified.code_hash,
                    "lp_deployment": (
                        vars(verified.lp_deployment) if verified.lp_deployment else None
                    ),
                    "gauge_code_hash": verified.gauge_code_hash,
                }
            )
        except Unavailable as exc:
            entry_error = str(exc)
            report.contracts.append(
                {
                    "strategy": strategy.name,
                    "address": strategy.address,
                    "status": "unavailable",
                    "note": entry_error,
                }
            )
        for name in scenario.assets:
            token = tokens[name]
            key = f"{strategy.name}/{name}"
            events: list[Action] = []
            report.actions[key] = events
            position = None
            baseline = None
            initial = None
            failure = entry_error
            failed_status = "unavailable-entry"
            try:
                if verified is None:
                    raise Unavailable(entry_error)
                price = prices.at(token, start.timestamp).usd
                initial = token.units(scenario.usd_value / price)
                if not initial:
                    raise Unavailable("starting amount rounds to zero")
                if strategy.kind == "gauge":
                    baseline = simulator.integrals(start, verified)
                entry = simulator.enter(start, verified, token, initial)
                position = Position(entry.amount, entry.dust)
                events.append(action("entry", scenario.start, start, entry))
            except Unavailable as exc:
                failure = str(exc)
            for date in dates:
                block = blocks[date]
                note = ""
                if position is None or verified is None or initial is None:
                    report.observations.append(
                        Observation(
                            strategy.name,
                            name,
                            date,
                            block,
                            failed_status,
                            token.quantity(initial) if initial is not None else None,
                            note=failure,
                        )
                    )
                    continue
                if baseline is not None and date != scenario.end:
                    try:
                        next_baseline = simulator.integrals(block, verified)
                        compound = simulator.compound(
                            block, verified, position.shares, baseline, position.idle
                        )
                        position.shares += compound.amount
                        coin = deposit_coin(strategy, CRV)
                        position.idle = {coin: compound.dust} if compound.dust else {}
                        baseline = next_baseline
                        events.append(action("compound", date, block, compound))
                    except Unaffordable as exc:
                        note = "compounding skipped; rewards retained: " + str(exc)
                        events.append(
                            Action(date, block, "skipped-compound", note=note)
                        )
                    except Unavailable as exc:
                        failure = "compounding data unavailable: " + str(exc)
                        failed_status = "incomplete"
                        report.observations.append(
                            Observation(
                                strategy.name,
                                name,
                                date,
                                block,
                                "incomplete",
                                token.quantity(initial),
                                note=failure,
                            )
                        )
                        position = None
                        continue
                try:
                    # An estimated exit does not change the position or its actions.
                    exit_result = simulator.exit(
                        block, verified, token, position.shares, baseline, position.idle
                    )
                    quantity = token.quantity(exit_result.amount + position.start_dust)
                    price = prices.at(token, block.timestamp).usd
                    value = quantity * price
                    hold = token.quantity(initial) * price
                    gas = (
                        sum((event.gas_usd for event in events), Decimal(0))
                        + exit_result.gas_usd
                    )
                    report.observations.append(
                        Observation(
                            strategy.name,
                            name,
                            date,
                            block,
                            "complete",
                            token.quantity(initial),
                            quantity,
                            value,
                            value / scenario.usd_value - 1,
                            value - hold,
                            gas,
                            None,
                            note,
                            exit_result.route,
                        )
                    )
                    if date == scenario.end:
                        events.append(action("exit", date, block, exit_result))
                except Unavailable as exc:
                    accounting = None
                    accounting_note = ""
                    try:
                        accounting = simulator.accounting(
                            block, verified, position.shares
                        )
                        accounting_note = (
                            "; accounting value excludes unclaimed rewards "
                            "and idle balances"
                        )
                    except Unavailable as accounting_error:
                        accounting_note = "; accounting value unavailable: " + str(
                            accounting_error
                        )
                    report.observations.append(
                        Observation(
                            strategy.name,
                            name,
                            date,
                            block,
                            "unavailable-exit",
                            token.quantity(initial),
                            gas_usd=sum(
                                (event.gas_usd for event in events), Decimal(0)
                            ),
                            accounting_usd=accounting,
                            note="; ".join(filter(None, (note, str(exc))))
                            + accounting_note,
                        )
                    )
    return report
