from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag
from rich.markup import escape
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from watch_price import clean_text, default_data_path, fetch_html, normalize_price


MAX_TRIES = 3
SKIP_TAGS = {"script", "style", "noscript", "svg", "path", "head"}
console = Console()


@dataclass
class Candidate:
    source: str
    text: str
    parsed_price: str
    css_selector: str
    xpath_selector: str
    attr: str | None
    currency: str | None
    score: tuple[int, int, int]


def css_escape(value: str) -> str:
    return re.sub(r"([^a-zA-Z0-9_-])", r"\\\1", value)


def slugify_host(hostname: str) -> str:
    value = hostname.lower().removeprefix("www.")
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-") or "site"


def currency_hint_from_soup(soup: BeautifulSoup) -> str | None:
    for selector in (
        'meta[property="product:price:currency"]',
        'meta[itemprop="priceCurrency"]',
        'meta[property="og:price:currency"]',
    ):
        node = soup.select_one(selector)
        if node is None:
            continue
        content = node.get("content")
        if isinstance(content, str) and content.strip().upper() in {"SEK", "KR"}:
            return "kr"
    return "kr" if " kr" in soup.get_text(" ", strip=True).lower() else None


def build_css_selector(element: Tag) -> str:
    if element.get("id"):
        return f"{element.name}#{css_escape(str(element['id']))}"

    for attr_name in ("property", "itemprop", "name", "data-testid"):
        attr_value = element.get(attr_name)
        if isinstance(attr_value, str) and attr_value:
            return f'{element.name}[{attr_name}="{css_escape(attr_value)}"]'

    segments: list[str] = []
    current: Tag | None = element
    while current is not None and current.name not in {None, "[document]"}:
        segment = current.name
        siblings = [
            sibling for sibling in current.parent.find_all(current.name, recursive=False)
        ] if current.parent else []
        if len(siblings) > 1:
            segment += f":nth-of-type({siblings.index(current) + 1})"
        segments.append(segment)
        current = current.parent if isinstance(current.parent, Tag) else None

    return " > ".join(reversed(segments))


def build_xpath_selector(element: Tag, attr: str | None = None) -> str:
    segments: list[str] = []
    current: Tag | None = element
    while current is not None and current.name not in {None, "[document]"}:
        siblings = [
            sibling for sibling in current.parent.find_all(current.name, recursive=False)
        ] if current.parent else []
        if current.parent is None or len(siblings) == 1:
            segments.append(current.name)
        else:
            segments.append(f"{current.name}[{siblings.index(current) + 1}]")
        current = current.parent if isinstance(current.parent, Tag) else None

    xpath = "/" + "/".join(reversed(segments))
    return f"{xpath}/@{attr}" if attr else xpath


def is_price_attribute(element: Tag, attr_name: str) -> bool:
    if attr_name == "data-price":
        return True
    if attr_name != "content":
        return False

    markers = []
    for key in ("property", "itemprop", "name"):
        value = element.get(key)
        if isinstance(value, str):
            markers.append(value.lower())
    return any("price" in marker or "pris" in marker for marker in markers)


def score_candidate(element: Tag, text: str, parsed_price: str, attr: str | None) -> tuple[int, int, int]:
    exact = 1 if text == parsed_price else 0
    attr_bonus = 1 if attr in {"data-price", "content"} else 0
    length_penalty = -min(len(text), 200)
    return (attr_bonus, exact, length_penalty)


def collect_candidates(html_text: str) -> list[Candidate]:
    soup = BeautifulSoup(html_text, "lxml")
    currency_hint = currency_hint_from_soup(soup)
    seen: set[tuple[str, str]] = set()
    candidates: list[Candidate] = []

    for element in soup.find_all(True):
        if element.name in SKIP_TAGS:
            continue

        text = clean_text(element.get_text(" ", strip=True))
        if text and len(text) <= 80:
            parsed_price = normalize_price(text)
            if parsed_price is not None:
                css_selector = build_css_selector(element)
                key = (css_selector, parsed_price)
                if key not in seen:
                    seen.add(key)
                    candidates.append(
                        Candidate(
                            source="text",
                            text=text,
                            parsed_price=parsed_price,
                            css_selector=css_selector,
                            xpath_selector=build_xpath_selector(element),
                            attr=None,
                            currency=None,
                            score=score_candidate(element, text, parsed_price, None),
                        )
                    )

        for attr_name, attr_value in element.attrs.items():
            if isinstance(attr_value, list) or not isinstance(attr_value, str):
                continue
            if not is_price_attribute(element, attr_name):
                continue
            parsed_price = normalize_price(attr_value, currency_hint)
            if parsed_price is None:
                continue
            css_selector = build_css_selector(element)
            key = (f"{css_selector}@{attr_name}", parsed_price)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                Candidate(
                    source=f"attr:{attr_name}",
                    text=attr_value,
                    parsed_price=parsed_price,
                    css_selector=css_selector,
                    xpath_selector=build_xpath_selector(element, attr_name),
                    attr=attr_name,
                    currency=currency_hint,
                    score=score_candidate(element, attr_value, parsed_price, attr_name),
                )
            )

    candidates.sort(key=lambda candidate: candidate.score, reverse=True)
    return candidates


def load_schema(schema_path: Path) -> dict[str, object]:
    if not schema_path.exists() or schema_path.stat().st_size == 0:
        return {"sites": []}
    with schema_path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    return data if isinstance(data, dict) else {"sites": []}


def save_schema(schema_path: Path, schema: dict[str, object]) -> None:
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    with schema_path.open("w", encoding="utf-8") as file:
        json.dump(schema, file, indent=2)
        file.write("\n")


def build_site_entry(url: str, chosen: Candidate, candidates: list[Candidate]) -> dict[str, object]:
    hostname = urlparse(url).hostname or ""
    site_candidates = [candidate for candidate in candidates if candidate.parsed_price == chosen.parsed_price]
    selectors: list[dict[str, str]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()

    for candidate in site_candidates[:6]:
        css_entry = {"type": "css", "value": candidate.css_selector}
        if candidate.attr:
            css_entry["attr"] = candidate.attr
        if candidate.currency:
            css_entry["currency"] = candidate.currency

        xpath_entry = {"type": "xpath", "value": candidate.xpath_selector}
        if candidate.attr and candidate.currency:
            xpath_entry["currency"] = candidate.currency

        for entry in (css_entry, xpath_entry):
            key = tuple(sorted(entry.items()))
            if key in seen:
                continue
            seen.add(key)
            selectors.append(entry)

    domains = [hostname.lower()]
    if hostname.startswith("www."):
        domains.append(hostname[4:].lower())
    else:
        domains.append(f"www.{hostname.lower()}")

    return {
        "name": slugify_host(hostname),
        "domains": domains,
        "selectors": selectors,
    }


def upsert_site(schema: dict[str, object], site_entry: dict[str, object]) -> None:
    sites = schema.setdefault("sites", [])
    if not isinstance(sites, list):
        schema["sites"] = []
        sites = schema["sites"]

    new_domains = {value for value in site_entry["domains"] if isinstance(value, str)}
    for index, site in enumerate(sites):
        if not isinstance(site, dict):
            continue
        existing_domains = {value for value in site.get("domains", []) if isinstance(value, str)}
        if existing_domains & new_domains:
            sites[index] = site_entry
            return
    sites.append(site_entry)


def prompt_yes_no(prompt: str) -> bool:
    return Confirm.ask(prompt, default=False)


def render_candidate(candidate: Candidate, index: int, total: int) -> None:
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column("Field", style="bold cyan", no_wrap=True)
    table.add_column("Value", style="white")
    table.add_row("Source", escape(candidate.source))
    table.add_row("Text", escape(candidate.text))
    table.add_row("Parsed", f"[bold green]{escape(candidate.parsed_price)}[/bold green]")
    table.add_row("CSS", escape(candidate.css_selector))
    if candidate.attr:
        table.add_row("Attr", escape(candidate.attr))
    table.add_row("XPath", escape(candidate.xpath_selector))

    console.print(
        Panel(
            table,
            title=f"Candidate {index}/{total}",
            border_style="blue",
            expand=False,
        )
    )


def discover(url: str, schema_path: Path, timeout_s: int) -> int:
    console.print(Panel.fit(f"[bold]Discover URL[/bold]\n{url}", border_style="magenta"))
    html_text = fetch_html(url, timeout_s)
    candidates = collect_candidates(html_text)
    if not candidates:
        console.print("[bold red]No price-like candidates were found in the server-rendered HTML.[/bold red]")
        return 1

    total = min(len(candidates), MAX_TRIES)
    for index, candidate in enumerate(candidates[:MAX_TRIES], start=1):
        render_candidate(candidate, index, total)
        if not prompt_yes_no("Does this look like the correct price?"):
            continue

        schema = load_schema(schema_path)
        site_entry = build_site_entry(url, candidate, candidates)
        upsert_site(schema, site_entry)
        save_schema(schema_path, schema)
        console.print(
            Panel.fit(
                (
                    f"[bold green]Saved schema[/bold green]\n"
                    f"Site: {site_entry['name']}\n"
                    f"Path: {schema_path}\n"
                    f"Fallback selectors: {len(site_entry['selectors'])}"
                ),
                border_style="green",
            )
        )
        return 0

    console.print("[bold yellow]No candidate was confirmed. No schema changes were saved.[/bold yellow]")
    return 1


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discover selector entries for a product page.")
    parser.add_argument("url", nargs="?", help="Product URL to inspect.")
    parser.add_argument("--schema-path", default=default_data_path("site_selectors.json"))
    parser.add_argument("--timeout", type=int, default=20)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    schema_path = Path(args.schema_path).expanduser()
    data_dir = schema_path.parent
    configured_data_dir = data_dir if data_dir.name != "data" or data_dir.is_absolute() else None

    url = args.url or Prompt.ask("Enter product URL").strip()
    if not url:
        console.print("[bold red]A URL is required.[/bold red]")
        return 1

    config_lines = [f"Schema path: {schema_path}"]
    if configured_data_dir is not None:
        config_lines.append(f"Data directory: {data_dir}")
    else:
        config_lines.append("Data directory: local repository data/")
        config_lines.append("Set PRICE_WATCHER_DATA_DIR or --schema-path to save into Koofr.")

    console.print(
        Panel.fit(
            "\n".join(config_lines),
            title="Discovery Config",
            border_style="cyan",
        )
    )

    return discover(url, schema_path, args.timeout)


if __name__ == "__main__":
    sys.exit(main())
