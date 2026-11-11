"""Shared command-line validation and Chinese interactive crawl settings."""

import argparse
import re


def keyword_value(value: str) -> str:
    """Strip a keyword without splitting meaningful spaces inside it."""
    keyword = value.strip()
    if not keyword:
        raise argparse.ArgumentTypeError("关键词不能为空。")
    return keyword


def positive_limit(value: str) -> int:
    """Accept a positive integer item limit."""
    try:
        limit = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("抓取数量必须是大于 0 的整数。") from None
    if limit <= 0:
        raise argparse.ArgumentTypeError("抓取数量必须是大于 0 的整数。")
    return limit


def add_crawl_arguments(parser: argparse.ArgumentParser) -> None:
    """Expose identical sampling options on both crawl entry points."""
    parser.add_argument(
        "--keyword", action="append", type=keyword_value, help="抓取关键词；可重复传入。"
    )
    parser.add_argument(
        "--limit", type=positive_limit, help="每个关键词最多抓取的去重商品数（正整数）。"
    )


def prompt_crawl_options(keywords: list[str] | None, limit: int | None) -> tuple[list[str], int]:
    """Prompt for missing settings, retrying invalid values before opening a browser."""
    while not keywords:
        raw = input("请输入关键词（多个关键词用中文或英文逗号分隔）：")
        try:
            keywords = [keyword_value(part) for part in re.split(r"[,，]", raw)]
        except argparse.ArgumentTypeError as exc:
            print(exc)
    while limit is None:
        try:
            limit = positive_limit(input("每个关键词最多抓取多少条商品（正整数）："))
        except argparse.ArgumentTypeError as exc:
            print(exc)
    keywords = list(dict.fromkeys(keywords))
    print(f"本次关键词：{'、'.join(keywords)}；每个关键词最多 {limit} 条去重商品。")
    return keywords, limit
