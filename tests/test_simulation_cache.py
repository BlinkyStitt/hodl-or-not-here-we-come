from decimal import Decimal

import pytest

from hodl.cache import Cache
from hodl.data import Archive, Prices
from hodl.model import Block, Unaffordable
from hodl.simulation import Execution, Simulator


def test_cached_action_and_unaffordable_result_reproduce_offline(tmp_path):
    path = tmp_path / "evidence.sqlite"
    cache = Cache(path)
    block = Block(14_000_000, "hash", 1640995200)
    simulator = Simulator(Archive("http://unused.invalid", cache), Prices(cache))
    expected = Execution(123, 2, 50000, 50000, Decimal("0.12"), ("route",), ())
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
