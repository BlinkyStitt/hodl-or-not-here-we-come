from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from hodl.cache import Cache
from hodl.catalog import CRV
from hodl.data import Archive, Prices
from hodl.model import Block, Unaffordable, Unavailable
from hodl.positions import GaugeState, RewardState
from hodl.simulation import Execution, Simulator


def test_display_changes_preserve_action_cache_but_accounting_changes_do_not(
    tmp_path, monkeypatch
):
    import hodl.simulation as module

    source = tmp_path / "hodl"
    source.mkdir()
    for path in Path(module.__file__).parent.glob("*.py"):
        (source / path.name).write_bytes(path.read_bytes())
    monkeypatch.setattr(module, "__file__", str(source / "simulation.py"))
    path = tmp_path / "evidence.sqlite"
    cache = Cache(path)
    block = Block(1, "hash", 1)
    simulator = Simulator(Archive("http://unused.invalid", cache), Prices(cache))
    expected = Execution(123, 0, 1, 1, Decimal(1), (), ())
    assert simulator.cached("enter", block, {}, lambda: expected) == expected
    cache.close()
    (source / "report.py").write_text("# A different display format\n")
    (source / "config.py").write_text("# A different configuration reader\n")
    cache = Cache(path, offline=True)

    def forbidden():
        pytest.fail("display change caused another simulation")

    simulator = Simulator(Archive("http://unused.invalid", cache), Prices(cache))
    assert simulator.cached("enter", block, {}, forbidden) == expected
    with localcontext() as context:
        context.prec = 50
        changed = Simulator(Archive("http://unused.invalid", cache), Prices(cache))
        with pytest.raises(Unavailable, match="cache miss"):
            changed.cached("enter", block, {}, forbidden)
    with (source / "positions.py").open("a") as stream:
        stream.write("\n# Changed accounting\n")
    simulator = Simulator(Archive("http://unused.invalid", cache), Prices(cache))
    with pytest.raises(Unavailable, match="cache miss"):
        simulator.cached("enter", block, {}, forbidden)
    cache.close()


def test_cached_action_and_unaffordable_result_reproduce_offline(tmp_path):
    path = tmp_path / "evidence.sqlite"
    cache = Cache(path)
    block = Block(14_000_000, "hash", 1640995200)
    simulator = Simulator(Archive("http://unused.invalid", cache), Prices(cache))
    state = GaugeState(
        10**20, 12345, 12300, block.timestamp, (RewardState(CRV, 42, (17 << 128) + 9),)
    )
    expected = Execution(123, 2, 50000, 50000, Decimal("0.12"), ("route",), (), state)
    assert simulator.cached("enter", block, {}, lambda: expected) == expected

    def unaffordable():
        raise Unaffordable("rewards below measured gas cost")

    with pytest.raises(Unaffordable, match="below measured"):
        simulator.cached("compound", block, {}, unaffordable)
    cache.close()
    cache = Cache(path, offline=True)
    simulator = Simulator(Archive("http://unused.invalid", cache), Prices(cache))

    def forbidden():
        pytest.fail("cached action executed again")

    assert simulator.cached("enter", block, {}, forbidden) == expected
    with pytest.raises(Unaffordable, match="below measured"):
        simulator.cached("compound", block, {}, forbidden)
    cache.close()
