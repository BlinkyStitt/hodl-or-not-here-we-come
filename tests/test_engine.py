import csv
import json
from dataclasses import replace
from decimal import Decimal

import pytest

from hodl.catalog import USDC, VerifiedStrategy, strategies
from hodl.data import Archive, Prices
from hodl.engine import compare
from hodl.model import Block, Price, Scenario, Unaffordable, Unavailable, parse_date
from hodl.positions import GaugeState
from hodl.report import export_csv
from hodl.simulation import Execution, Simulator


class FixtureArchive(Archive):
    def __init__(self):
        pass

    def at(self, timestamp, ceiling):
        return Block(timestamp // 12, hex(timestamp), timestamp)


class FixturePrices(Prices):
    def __init__(self):
        pass

    def at(self, token, timestamp):
        return Price(Decimal(1), timestamp, "test fixture")


class FixtureSimulator(Simulator):
    def __init__(self, *, skip=False, missing=False):
        self.engine = {"source": "test fixture"}
        self.entries = []
        self.exits = []
        self.exit_states = []
        self.compounds = []
        self.skip = skip
        self.missing = missing

    @staticmethod
    def result(amount, cost, state=None):
        return Execution(amount, 0, cost, cost, Decimal(cost), (), (), state)

    def enter(self, block, verified, source, amount):
        self.entries.append((block, amount))
        state = (
            GaugeState(block.timestamp, 0, 0, block.timestamp, ())
            if verified.gauge
            else None
        )
        return self.result(amount - 10 * 10**6, 10, state)

    def exit(self, block, verified, target, shares, state, idle):
        self.exits.append(shares)
        self.exit_states.append(state)
        return self.result(
            shares - 5 * 10**6,
            5,
            replace(state, fraction=999, minted=999) if state else None,
        )

    def compound(self, block, verified, shares, state, idle):
        self.compounds.append((shares, state))
        if self.missing:
            raise Unavailable("unsupported reward token")
        if self.skip and len(self.compounds) == 1:
            raise Unaffordable("rewards below gas cost")
        return self.result(
            10 * 10**6,
            2,
            GaugeState(
                block.timestamp,
                state.fraction + 10,
                state.minted + 10,
                block.timestamp,
                (),
            ),
        )


@pytest.fixture
def setup(monkeypatch):
    def verified(archive, strategy, block):
        return VerifiedStrategy(
            strategy, block, "gauge" if strategy.kind == "gauge" else None, None, "code"
        )

    monkeypatch.setattr("hodl.engine.verify", verified)
    scenario = Scenario(
        parse_date("2022-01-01"), parse_date("2022-04-01"), ("USD",), Decimal(100)
    )
    return (
        scenario,
        FixtureArchive(),
        FixturePrices(),
        Block(999999999, "ceiling", scenario.end),
    )


def run_fixture(setup, simulator, strategy_name):
    scenario, archive, prices, ceiling = setup
    selected = tuple(s for s in strategies() if s.name == strategy_name)
    return compare(scenario, selected, archive, prices, simulator, ceiling)


def test_observations_keep_shares_and_entry_cost_occurs_once(setup):
    simulator = FixtureSimulator()
    report = run_fixture(setup, simulator, "yearn-usdc-v2")
    rows = [row for row in report.observations if row.strategy == "yearn-usdc-v2"]
    assert len(simulator.entries) == 1
    assert simulator.exits == [90 * 10**6] * 3
    assert [row.end_quantity for row in rows] == [Decimal(85)] * 3
    assert [row.gas_usd for row in rows] == [Decimal(15)] * 3
    assert [row.net_return for row in rows] == [Decimal("-0.15")] * 3
    assert [row.versus_hold_usd for row in rows] == [Decimal(-15)] * 3
    assert not simulator.compounds
    assert [event.kind for event in report.actions["yearn-usdc-v2/USD"]] == [
        "entry",
        "exit",
    ]


def test_monthly_compounding_changes_shares_but_final_exit_does_not_compound(setup):
    simulator = FixtureSimulator()
    report = run_fixture(setup, simulator, "curve-3pool-gauge")
    assert simulator.exits == [100 * 10**6, 110 * 10**6, 110 * 10**6]
    assert [shares for shares, _ in simulator.compounds] == [90 * 10**6, 100 * 10**6]
    assert [state.minted for _, state in simulator.compounds] == [0, 10]
    assert [state.minted for state in simulator.exit_states] == [10, 20, 20]
    assert simulator.exit_states[0] == simulator.compounds[1][1]
    rows = [row for row in report.observations if row.strategy == "curve-3pool-gauge"]
    assert rows[-1].end_quantity == Decimal(105)
    assert rows[-1].gas_usd == Decimal(19)
    assert [event.kind for event in report.actions["curve-3pool-gauge/USD"]] == [
        "entry",
        "compound",
        "compound",
        "exit",
    ]


def test_rewards_below_cost_keep_original_checkpoint_and_principal(setup):
    simulator = FixtureSimulator(skip=True)
    report = run_fixture(setup, simulator, "curve-3pool-gauge")
    assert simulator.exits == [90 * 10**6, 100 * 10**6, 100 * 10**6]
    assert simulator.compounds[0] == simulator.compounds[1]
    assert [state.minted for state in simulator.exit_states] == [0, 10, 10]
    events = report.actions["curve-3pool-gauge/USD"]
    assert events[1].kind == "skipped-compound"
    assert events[1].gas_usd == 0
    assert "retained" in events[1].note


def test_missing_compounding_data_is_not_a_complete_net_outcome(setup):
    simulator = FixtureSimulator(missing=True)
    report = run_fixture(setup, simulator, "curve-3pool-gauge")
    rows = [row for row in report.observations if row.strategy == "curve-3pool-gauge"]
    assert [row.status for row in rows] == ["incomplete"] * 3
    assert [row.net_return for row in rows] == [None] * 3
    assert simulator.exits == []


def test_all_asset_benchmarks_and_cash_remain_when_filtered(setup):
    report = run_fixture(setup, FixtureSimulator(), "yearn-usdc-v2")
    assert {row.strategy for row in report.observations} == {
        "yearn-usdc-v2",
        "hold-USD",
        "hold-BTC",
        "hold-ETH",
        "hold-CRV",
        "cash-USD",
    }


def test_csv_uses_same_full_values_and_has_source_manifest(setup, tmp_path):
    report = run_fixture(setup, FixtureSimulator(), "yearn-usdc-v2")
    path = tmp_path / "comparison.csv"
    export_csv(report, path)
    with path.open() as stream:
        rows = list(csv.DictReader(stream))
    row = next(r for r in rows if r["strategy"] == "yearn-usdc-v2")
    assert row["start_quantity"] == "100"
    assert row["end_quantity"] == "85"
    assert row["net_return_fraction"] == "-0.15"
    assert row["token_return_fraction"] == "-0.15"
    assert row["best_strategy"] == "hold-USD"
    assert row["best_asset"] == "USD"
    assert row["versus_best_usd"] == "-15"
    assert row["single_vault_strategy"] == "yearn-usdc-v2"
    assert row["versus_single_vault_usd"] == "0"
    metadata = json.loads(path.with_suffix(".json").read_text())
    assert metadata["assets"]["USD"]["address"] == USDC.address
    assert metadata["actions"]["yearn-usdc-v2/USD"][0]["kind"] == "entry"
