from __future__ import annotations

import csv
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

try:
    from lxml import html as lxml_html  # type: ignore
except Exception:
    lxml_html = None


DEFAULT_URL = (
    "https://www.cervera.se/produkt/rorstrand-mon-amie-mon-amie-mugg-34cl-4-pack-med-hankel"
)
DEFAULT_LINKS_CSV = "data/links.csv"
DEFAULT_STATE_PATH = "data/price_memory.json"


SELECTORS = [
    ("css", ".ProductInfoBlock_pdpPrice__eB8Io > span:nth-child(1)"),
    (
        "css",
        (
            "span.ProductPrice_price___B9X_.ProductInfoBlock_pdpPrice__eB8Io."
            "ProductInfoBlock_pdpSalePrice__6qtS6 span"
        ),
    ),
    ("xpath", "/html/body/div[2]/main/section/div/div[3]/div[1]/div/div[1]/span[1]/span"),
]


def clean_text(value: str) -> str:
    return " ".join(value.split())


def parse_price(value: str) -> str | None:
    match = re.search(r"\d[\d\s.,]*\s*kr", value, flags=re.IGNORECASE)
    return clean_text(match.group(0)) if match else None


def parse_price_amount(value: str) -> float | None:
    price = parse_price(value)
    if price is None:
        return None

    normalized = re.sub(r"\s*kr\s*$", "", price, flags=re.IGNORECASE)
    normalized = normalized.replace(" ", "").replace(",", ".")
    if "." in normalized and normalized.count(".") > 1:
        parts = normalized.split(".")
        normalized = "".join(parts[:-1]) + "." + parts[-1]

    try:
        return float(normalized)
    except ValueError:
        return None


def fetch_html(url: str, timeout_s: int) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "sv-SE,sv;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    response = requests.get(url, headers=headers, timeout=timeout_s)
    response.raise_for_status()
    return response.text


def load_state(state_path: str) -> dict[str, dict[str, str]]:
    path = Path(state_path)
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        return {}

    state: dict[str, dict[str, str]] = {}
    for url, entry in data.items():
        if isinstance(url, str) and isinstance(entry, dict):
            state[url] = {
                key: value
                for key, value in entry.items()
                if isinstance(key, str) and isinstance(value, str)
            }
    return state


def save_state(state_path: str, state: dict[str, dict[str, str]]) -> None:
    path = Path(state_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(state, file, indent=2, sort_keys=True)
        file.write("\n")


def read_links(csv_path: str) -> list[str]:
    path = Path(csv_path)
    if not path.exists():
        return []

    links: list[str] = []
    with path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.reader(file)
        for row in reader:
            for cell in row:
                value = cell.strip().strip('"').strip("'")
                if value.startswith(("http://", "https://")):
                    links.append(value)
    return links


def try_xpath(html_text: str, xpath: str) -> str | None:
    if lxml_html is None:
        return None

    tree = lxml_html.fromstring(html_text)
    result = tree.xpath(xpath)
    if not result:
        return None

    node = result[0]
    raw = node.text_content() if hasattr(node, "text_content") else str(node)
    return clean_text(raw)


def build_item_message(
    current_price: str,
    previous_entry: dict[str, str] | None,
    today_iso: str,
) -> str:
    if previous_entry is None:
        return f"Current price: {current_price}"

    previous_price = previous_entry.get("price")
    if previous_price == current_price:
        return f"The item remains at {current_price}."

    previous_amount = parse_price_amount(previous_price or "")
    current_amount = parse_price_amount(current_price)
    if previous_amount is not None and current_amount is not None:
        direction = "increased" if current_amount > previous_amount else "decreased"
    else:
        direction = "changed"

    return (
        f"On {today_iso}, the item's price {direction} "
        f"from {previous_price or 'unknown'} to {current_price}."
    )


def print_selector_results(url: str, html_text: str) -> str | None:
    soup = BeautifulSoup(html_text, "html.parser")
    print(f"[url] {url}")
    print("[selector_results]")
    found_any = False
    parsed_price: str | None = None

    for selector_type, selector in SELECTORS:
        if selector_type == "css":
            node = soup.select_one(selector)
            text = clean_text(node.get_text(" ", strip=True)) if node else None
        else:
            text = try_xpath(html_text, selector)

        price = parse_price(text) if text else None
        print(f"- {selector_type}: {selector}")
        if text:
            found_any = True
            print(f"  text: {text}")
            print(f"  parsed_price: {price or 'N/A'}")
            if parsed_price is None and price is not None:
                parsed_price = price
        else:
            if selector_type == "xpath" and lxml_html is None:
                print("  text: <skipped, install lxml to evaluate xpath>")
            else:
                print("  text: <no match>")

    if not found_any:
        print("No selector matched. The page might be JS-rendered or class names changed.")
    return parsed_price


def main() -> int:
    csv_path = os.getenv("LINKS_CSV_PATH", DEFAULT_LINKS_CSV)
    state_path = os.getenv("PRICE_STATE_PATH", DEFAULT_STATE_PATH)
    urls = read_links(csv_path)
    if not urls:
        urls = [os.getenv("FETCH_URL", DEFAULT_URL)]

    timeout_s = int(os.getenv("FETCH_TIMEOUT_SECONDS", "20"))
    today_iso = date.today().isoformat()
    state = load_state(state_path)
    print(f"[links_source] {csv_path}")
    print(f"[links_count] {len(urls)}")
    print(f"[state_path] {state_path}")

    matches = 0
    failures = 0
    item_messages: list[str] = []
    updated_state = state.copy()
    for index, url in enumerate(urls, start=1):
        print(f"\n=== Link {index}/{len(urls)} ===")
        try:
            html_text = fetch_html(url, timeout_s)
        except requests.RequestException as exc:
            failures += 1
            print(f"[url] {url}")
            print(f"[error] {exc}")
            continue

        price = print_selector_results(url, html_text)
        if price:
            matches += 1
            message = build_item_message(price, state.get(url), today_iso)
            print(f"[item_message] {message}")
            item_messages.append(message)
            updated_state[url] = {
                "last_checked": today_iso,
                "last_message": message,
                "price": price,
            }

    save_state(state_path, updated_state)
    print("\n[summary]")
    print(f"matched_links: {matches}")
    print(f"failed_links: {failures}")
    print(f"total_links: {len(urls)}")
    print(f"item_messages: {len(item_messages)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
