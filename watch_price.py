from __future__ import annotations

import csv
import os
import re
import sys
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


def print_selector_results(url: str, html_text: str) -> bool:
    soup = BeautifulSoup(html_text, "html.parser")
    print(f"[url] {url}")
    print("[selector_results]")
    found_any = False

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
        else:
            if selector_type == "xpath" and lxml_html is None:
                print("  text: <skipped, install lxml to evaluate xpath>")
            else:
                print("  text: <no match>")

    if not found_any:
        print("No selector matched. The page might be JS-rendered or class names changed.")
    return found_any


def main() -> int:
    csv_path = os.getenv("LINKS_CSV_PATH", DEFAULT_LINKS_CSV)
    urls = read_links(csv_path)
    if not urls:
        urls = [os.getenv("FETCH_URL", DEFAULT_URL)]

    timeout_s = int(os.getenv("FETCH_TIMEOUT_SECONDS", "20"))
    print(f"[links_source] {csv_path}")
    print(f"[links_count] {len(urls)}")

    matches = 0
    failures = 0
    for index, url in enumerate(urls, start=1):
        print(f"\n=== Link {index}/{len(urls)} ===")
        try:
            html_text = fetch_html(url, timeout_s)
        except requests.RequestException as exc:
            failures += 1
            print(f"[url] {url}")
            print(f"[error] {exc}")
            continue

        if print_selector_results(url, html_text):
            matches += 1

    print("\n[summary]")
    print(f"matched_links: {matches}")
    print(f"failed_links: {failures}")
    print(f"total_links: {len(urls)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
