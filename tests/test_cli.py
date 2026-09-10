import pytest

from hodl.cli import main, parser


@pytest.fixture(autouse=True)
def isolated_configuration(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)


def test_project_env_is_loaded_with_environment_and_cli_precedence(
    monkeypatch, tmp_path
):
    monkeypatch.delenv("HODL_RPC_URL", raising=False)
    (tmp_path / ".env").write_text('HODL_RPC_URL="http://project.invalid"\n')
    assert parser().parse_args(["list"]).rpc_url == "http://project.invalid"
    monkeypatch.setenv("HODL_RPC_URL", "http://environment.invalid")
    assert parser().parse_args(["list"]).rpc_url == "http://environment.invalid"
    assert (
        parser().parse_args(["list", "--rpc-url", "http://explicit.invalid"]).rpc_url
        == "http://explicit.invalid"
    )


def test_default_end_replays_offline_from_reported_timestamp(monkeypatch, tmp_path):
    import json
    from decimal import Decimal

    from hodl.data import Archive
    from hodl.engine import Report
    from hodl.model import Block, Observation, parse_date

    end = Block(14_000_000, "0xfinalized", parse_date("2022-02-01"))
    monkeypatch.setenv("HODL_RPC_URL", "http://test.invalid")
    monkeypatch.setattr(Archive, "check_mainnet", lambda self: None)
    monkeypatch.setattr(Archive, "finalized", lambda self: end)

    def compare(scenario, selected, archive, prices, simulator, ceiling):
        assert ceiling == end
        row = Observation(
            "cash-USD",
            "cash",
            scenario.end,
            ceiling,
            "complete",
            end_usd=Decimal(10000),
        )
        return Report(scenario, ceiling, ceiling, [row], {}, [], {})

    monkeypatch.setattr("hodl.cli.compare", compare)
    args = ["compare", "--start", "2022-01-01", "--cache", str(tmp_path / "cache")]
    first = tmp_path / "online.csv"
    assert main([*args, "--csv", str(first)]) == 0
    metadata = json.loads(first.with_suffix(".json").read_text())
    reported_end = Block(**metadata["end_block"]).date

    def forbidden(*args):
        raise AssertionError("offline run contacted the archive")

    monkeypatch.setattr(Archive, "request", forbidden)
    monkeypatch.setattr(Archive, "finalized", forbidden)
    second = tmp_path / "offline.csv"
    assert main([*args, "--end", reported_end, "--offline", "--csv", str(second)]) == 0
    assert first.read_bytes() == second.read_bytes()
    assert (
        first.with_suffix(".json").read_bytes()
        == second.with_suffix(".json").read_bytes()
    )


def test_cli_requires_start():
    import pytest

    with pytest.raises(SystemExit) as exc:
        main(["compare"])
    assert exc.value.code == 2


def test_cli_reports_missing_archive_configuration(monkeypatch, capsys):
    monkeypatch.delenv("HODL_RPC_URL", raising=False)
    assert main(["compare", "--start", "2022-01-01"]) == 2
    assert "HODL_RPC_URL" in capsys.readouterr().err


def test_list_keeps_unverified_contracts_visible(monkeypatch, capsys):
    monkeypatch.delenv("HODL_RPC_URL", raising=False)
    assert main(["list"]) == 2
    output = capsys.readouterr().out
    assert "yearn-usd-v3" in output
    assert "0x696d02Db93291651ED510704c9b286841d506987" in output
    assert "supported dates=unverified" in output


def test_unknown_strategy_reports_error(monkeypatch, capsys):
    monkeypatch.delenv("HODL_RPC_URL", raising=False)
    assert (
        main(["compare", "--start", "2022-01-01", "--strategy", "not-a-strategy"]) == 2
    )
    assert "unknown strategy: not-a-strategy" in capsys.readouterr().err
