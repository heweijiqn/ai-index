"""Validate CLI and interactive settings before any browser or history access."""

import pytest

import crawler
import run_daily
from crawl_options import prompt_crawl_options


@pytest.mark.parametrize("module", [crawler, run_daily])
def test_repeated_keyword_and_limit_cli(module):
    args = module._build_arg_parser().parse_args(
        ["--keyword", " AI 副业 ", "--keyword", "Sora 教程", "--limit", "101"]
    )
    assert args.keyword == ["AI 副业", "Sora 教程"]
    assert args.limit == 101


@pytest.mark.parametrize("module", [crawler, run_daily])
@pytest.mark.parametrize(
    "arguments", [["--keyword", " "], *[["--limit", value] for value in ("0", "-1", "1.5", "abc")]]
)
def test_invalid_cli_values_fail_before_running(module, arguments):
    with pytest.raises(SystemExit) as exc:
        module._build_arg_parser().parse_args(arguments)
    assert exc.value.code == 2


def test_interactive_retries_and_preserves_spaces(monkeypatch, capsys):
    answers = iter([" ", "AI 副业,", " AI 副业，Sora 教程,AI 副业 ", "0", "abc", "100"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert prompt_crawl_options(None, None) == (["AI 副业", "Sora 教程"], 100)
    output = capsys.readouterr().out
    assert "关键词不能为空" in output
    assert "抓取数量必须" in output


def test_interactive_supplied_values_do_not_prompt(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("unexpected prompt"))
    assert prompt_crawl_options(["AI 副业"], 20) == (["AI 副业"], 20)


@pytest.mark.parametrize("keywords,limit", [([], 10), ([" "], 10), (None, 0), (None, True)])
def test_invalid_programmatic_settings_never_start_browser(keywords, limit):
    with pytest.raises(ValueError):
        crawler.crawl_all(keywords=keywords, limit=limit)
