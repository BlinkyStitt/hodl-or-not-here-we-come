from hodl.cli import main


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
