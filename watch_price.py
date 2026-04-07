from __future__ import annotations

import csv
import html
import json
import time
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag

try:
    from lxml import html as lxml_html  # type: ignore
except Exception:
    lxml_html = None


DEFAULT_URL = (
    "https://www.cervera.se/produkt/rorstrand-mon-amie-mon-amie-mugg-34cl-4-pack-med-hankel"
)
DEFAULT_WATCH_MODE = "price"
DEFAULT_DATA_DIR_ENV = "PRICE_WATCHER_DATA_DIR"
DEFAULT_LINKS_CSV = "links.csv"
DEFAULT_STATE_PATH = "price_memory.json"
DEFAULT_SELECTOR_SCHEMA_PATH = "site_selectors.json"
DEFAULT_DISCOUNT_CONFIG_PATH = "discount_watchers.json"
DEFAULT_DISCOUNT_STATE_PATH = "discount_memory.json"


DEFAULT_SELECTOR_SCHEMA = {
    "sites": [
        {
            "name": "cervera",
            "domains": ["cervera.se", "www.cervera.se"],
            "selectors": [
                {"type": "css", "value": ".ProductInfoBlock_pdpPrice__eB8Io > span:nth-child(1)"},
                {
                    "type": "css",
                    "value": (
                        "span.ProductPrice_price___B9X_.ProductInfoBlock_pdpPrice__eB8Io."
                        "ProductInfoBlock_pdpSalePrice__6qtS6 span"
                    ),
                },
                {
                    "type": "xpath",
                    "value": "/html/body/div[2]/main/section/div/div[3]/div[1]/div/div[1]/span[1]/span",
                },
            ],
        }
    ]
}


DEFAULT_DISCOUNT_CONFIG = {"watches": []}
PRODUCT_ID_RE = re.compile(r"/pl/\d+-(\d+)(?:/|$)")


@dataclass(frozen=True)
class DiscountMatch:
    title: str
    discount_percent: int
    product_url: str | None = None


def default_data_path(filename: str) -> str:
    data_dir = os.getenv(DEFAULT_DATA_DIR_ENV)
    if data_dir:
        return str(Path(data_dir).expanduser() / filename)
    return str(Path("data") / filename)


def clean_text(value: str) -> str:
    return " ".join(value.split())


def parse_price(value: str) -> str | None:
    match = re.search(r"\d[\d\s.,]*\s*kr", value, flags=re.IGNORECASE)
    return clean_text(match.group(0)) if match else None


def normalize_price(value: str, currency_hint: str | None = None) -> str | None:
    parsed = parse_price(value)
    if parsed is not None:
        return parsed

    if currency_hint is None:
        return None

    normalized = value.strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    if not re.fullmatch(r"\d+(?:\.\d+)?", normalized):
        return None

    integer_part, dot, fractional_part = normalized.partition(".")
    grouped_integer = f"{int(integer_part):,}".replace(",", " ")
    if dot and fractional_part.strip("0"):
        return f"{grouped_integer}.{fractional_part.rstrip('0')} {currency_hint}"
    return f"{grouped_integer} {currency_hint}"


def parse_price_amount(value: str) -> float | None:
    price = normalize_price(value)
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


def parse_discount_percent(value: str) -> int | None:
    match = re.search(r"-\s*(\d+)\s*%", value)
    if match is None:
        return None
    return int(match.group(1))


def infer_country_code_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    parts = hostname.split(".")
    tld = parts[-1] if parts else ""
    if len(tld) == 2 and tld.isalpha():
        return tld.upper()

    first_segment = parsed.path.strip("/").split("/", 1)[0]
    if len(first_segment) == 2 and first_segment.isalpha():
        return first_segment.upper()

    return None


def infer_product_id_from_url(url: str) -> str | None:
    match = PRODUCT_ID_RE.search(urlparse(url).path)
    return match.group(1) if match else None


def coerce_positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        return int(value) if value > 0 and value.is_integer() else None
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


def fetch_html(url: str, timeout_s: int) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "sv-SE,sv;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": "https://www.pricerunner.se/",
        "Upgrade-Insecure-Requests": "1",
    }
    last_error: requests.RequestException | None = None
    for attempt in range(1, 4):
        try:
            response = requests.get(url, headers=headers, timeout=timeout_s)
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            last_error = exc
            if attempt == 3:
                break
            time.sleep(attempt)

    raise last_error if last_error is not None else requests.RequestException(
        "Unknown fetch error"
    )


def load_selector_schema(schema_path: str) -> dict[str, object]:
    path = Path(schema_path)
    if not path.exists():
        return DEFAULT_SELECTOR_SCHEMA

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    return data if isinstance(data, dict) else DEFAULT_SELECTOR_SCHEMA


def load_discount_config(config_path: str) -> dict[str, object]:
    path = Path(config_path)
    if not path.exists():
        return DEFAULT_DISCOUNT_CONFIG

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    return data if isinstance(data, dict) else DEFAULT_DISCOUNT_CONFIG


def load_state(state_path: str) -> dict[str, dict[str, str]]:
    path = Path(state_path)
    if not path.exists():
        return {}
    if path.stat().st_size == 0:
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


def normalize_selectors(raw_selectors: object) -> list[dict[str, str]]:
    selectors: list[dict[str, str]] = []
    if not isinstance(raw_selectors, list):
        return selectors

    for entry in raw_selectors:
        if not isinstance(entry, dict):
            continue
        selector_type = entry.get("type")
        selector_value = entry.get("value")
        if selector_type in {"css", "xpath"} and isinstance(selector_value, str):
            selector_entry = {"type": selector_type, "value": selector_value}
            attr = entry.get("attr")
            currency = entry.get("currency")
            if isinstance(attr, str):
                selector_entry["attr"] = attr
            if isinstance(currency, str):
                selector_entry["currency"] = currency
            selectors.append(selector_entry)
    return selectors


def normalize_discount_watches(raw_watches: object) -> list[dict[str, object]]:
    watches: list[dict[str, object]] = []
    if not isinstance(raw_watches, list):
        return watches

    for entry in raw_watches:
        if not isinstance(entry, dict):
            continue

        name = entry.get("name")
        url = entry.get("url")
        item_selector = entry.get("item_selector")
        discount_selector = entry.get("discount_selector")
        min_discount_percent = coerce_positive_int(entry.get("min_discount_percent"))
        if not (
            isinstance(name, str)
            and isinstance(url, str)
            and isinstance(item_selector, str)
            and isinstance(discount_selector, str)
            and min_discount_percent is not None
        ):
            continue

        watch: dict[str, object] = {
            "name": name,
            "url": url,
            "item_selector": item_selector,
            "discount_selector": discount_selector,
            "min_discount_percent": min_discount_percent,
        }

        title_selector = entry.get("title_selector")
        title_attr = entry.get("title_attr")
        max_items = coerce_positive_int(entry.get("max_items"))
        if isinstance(title_selector, str):
            watch["title_selector"] = title_selector
        if isinstance(title_attr, str):
            watch["title_attr"] = title_attr
        if max_items is not None:
            watch["max_items"] = max_items

        watches.append(watch)

    return watches


def host_matches(hostname: str, domain: str) -> bool:
    normalized_host = hostname.lower()
    normalized_domain = domain.lower()
    return normalized_host == normalized_domain or normalized_host.endswith(f".{normalized_domain}")


def get_selectors_for_url(url: str, schema: dict[str, object]) -> tuple[str | None, list[dict[str, str]]]:
    hostname = urlparse(url).hostname or ""
    sites = schema.get("sites")
    if not isinstance(sites, list):
        return None, []

    for site in sites:
        if not isinstance(site, dict):
            continue

        domains = site.get("domains", [])
        url_contains = site.get("url_contains", [])
        if not isinstance(domains, list) or not all(isinstance(value, str) for value in domains):
            continue
        if not isinstance(url_contains, list) or not all(isinstance(value, str) for value in url_contains):
            url_contains = []

        if domains and not any(host_matches(hostname, domain) for domain in domains):
            continue
        if url_contains and not any(pattern in url for pattern in url_contains):
            continue

        selectors = normalize_selectors(site.get("selectors"))
        if selectors:
            name = site.get("name")
            return (name if isinstance(name, str) else None, selectors)

    return None, []


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


def extract_node_text(node: Tag | None, attr: str | None = None) -> str | None:
    if node is None:
        return None

    if attr is not None:
        attr_value = node.get(attr)
        if attr_value is None:
            return None
        return clean_text(str(attr_value))

    return clean_text(node.get_text(" ", strip=True))


def derive_discount_title(
    item_node: Tag,
    title_selector: str | None,
    title_attr: str | None,
    discount_text: str | None,
) -> str:
    candidate_selectors: list[tuple[str, str | None]] = []
    if title_selector is not None:
        candidate_selectors.append((title_selector, title_attr))
    candidate_selectors.extend(
        [
            ("h1", "title"),
            ("h1", None),
            ("h2", "title"),
            ("h2", None),
            ("h3", "title"),
            ("h3", None),
            ("img", "alt"),
            ("[title]", "title"),
        ]
    )

    for selector, attr in candidate_selectors:
        node = item_node.select_one(selector)
        text = extract_node_text(node, attr)
        if text:
            return text.removeprefix("Kylfrysar ").strip()

    text = clean_text(item_node.get_text(" ", strip=True))
    if discount_text and text.startswith(discount_text):
        text = text[len(discount_text):].strip()
    text = re.sub(r"^\d+\s+", "", text)
    return text


def derive_discount_product_url(item_node: Tag, watch_url: str) -> str | None:
    parent_anchor = item_node.find_parent("a", href=True)
    if parent_anchor is not None:
        href = parent_anchor.get("href")
        if isinstance(href, str) and href.strip():
            return urljoin(watch_url, href.strip())

    direct_anchor = item_node.select_one("a[href]")
    if direct_anchor is not None:
        href = direct_anchor.get("href")
        if isinstance(href, str) and href.strip():
            return urljoin(watch_url, href.strip())

    return None


def build_discount_alert_key(matches: list[DiscountMatch]) -> str:
    return "\n".join(
        f"{match.discount_percent}|{match.title}"
        for match in matches
    )


def build_discount_state_key(watch: dict[str, object]) -> str:
    name = str(watch.get("name", "")).strip()
    url = str(watch.get("url", "")).strip()
    threshold = str(watch.get("min_discount_percent", "")).strip()
    return f"{name}|{url}|{threshold}"


def build_discount_match_state_key(match: DiscountMatch) -> str:
    return match.product_url or match.title


def build_discount_match_state_value(matches: list[DiscountMatch]) -> str:
    return "\n".join(build_discount_match_state_key(match) for match in matches)


def parse_discount_match_state_value(value: str | None) -> set[str]:
    if not value:
        return set()
    return {line for line in value.splitlines() if line}


def extract_discount_matches(
    html_text: str,
    watch: dict[str, object],
) -> list[DiscountMatch]:
    soup = BeautifulSoup(html_text, "html.parser")
    item_selector = str(watch["item_selector"])
    discount_selector = str(watch["discount_selector"])
    min_discount_percent = int(watch["min_discount_percent"])
    title_selector = watch.get("title_selector")
    title_attr = watch.get("title_attr")
    max_items = watch.get("max_items")
    watch_url = str(watch["url"])

    matches: list[DiscountMatch] = []
    seen: set[tuple[int, str]] = set()
    for item_node in soup.select(item_selector):
        discount_text = extract_node_text(item_node.select_one(discount_selector))
        if not discount_text:
            continue

        discount_percent = parse_discount_percent(discount_text)
        if discount_percent is None or discount_percent < min_discount_percent:
            continue

        title = derive_discount_title(
            item_node,
            title_selector if isinstance(title_selector, str) else None,
            title_attr if isinstance(title_attr, str) else None,
            discount_text,
        )
        product_url = derive_discount_product_url(item_node, watch_url)
        key = (discount_percent, title)
        if key in seen:
            continue
        seen.add(key)
        matches.append(
            DiscountMatch(
                title=title,
                discount_percent=discount_percent,
                product_url=product_url,
            )
        )

        if isinstance(max_items, int) and len(matches) >= max_items:
            break

    return matches


def print_discount_watch_results(
    watch: dict[str, object],
    matches: list[DiscountMatch],
) -> None:
    watch_name = str(watch["name"])
    print(f"[watch] {watch['name']}")
    print(f"[url] {watch['url']}")
    print(f"[threshold_percent] {watch['min_discount_percent']}")
    print("[discount_results]")
    if not matches:
        print("No discounts met the threshold.")
    for match in matches:
        print(f"- -{match.discount_percent}% | {match.title}")
    print(
        "[watch_result] "
        f"{watch_name}: {len(matches)} discounts at or above {watch['min_discount_percent']}%"
    )


def format_money_amount(
    amount: float | None,
    currency_code: str,
    *,
    round_to_whole: bool = False,
) -> str:
    if amount is None:
        return "unknown"

    normalized_currency = currency_code.upper()
    if round_to_whole:
        amount = float(round(amount))
    rounded = round(amount)
    if abs(amount - rounded) < 0.005:
        number_text = f"{rounded:,}".replace(",", " ")
    else:
        number_text = f"{amount:,.2f}".replace(",", " ").replace(".", ",")

    if normalized_currency == "SEK":
        return f"{number_text} kr"
    return f"{number_text} {normalized_currency}"


def format_discount_percent(discount_percent: int) -> str:
    return f"-{discount_percent}%"


def compute_time_weighted_average_price(
    history: list[dict[str, object]],
    *,
    end_time: datetime | None = None,
) -> float | None:
    points: list[tuple[datetime, float]] = []
    for point in history:
        if not isinstance(point, dict):
            continue
        timestamp = point.get("timestamp")
        price = point.get("price")
        if not isinstance(timestamp, str) or not isinstance(price, (int, float)):
            continue
        try:
            parsed_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        points.append((parsed_time, float(price)))

    if not points:
        return None
    if len(points) == 1:
        return points[0][1]

    points.sort(key=lambda entry: entry[0])
    final_time = end_time
    if final_time is None:
        final_time = datetime.now(points[-1][0].tzinfo)
    if final_time < points[-1][0]:
        final_time = points[-1][0]

    weighted_sum = 0.0
    total_seconds = 0.0
    for index, (start_time, price) in enumerate(points):
        if index + 1 < len(points):
            end = points[index + 1][0]
        else:
            end = final_time
        duration_seconds = max((end - start_time).total_seconds(), 0.0)
        if duration_seconds == 0:
            continue
        weighted_sum += price * duration_seconds
        total_seconds += duration_seconds

    if total_seconds == 0:
        return points[-1][1]
    return weighted_sum / total_seconds


def fetch_discount_price_summary(product_url: str, timeout_s: int) -> dict[str, str] | None:
    product_id = infer_product_id_from_url(product_url)
    country_code = infer_country_code_from_url(product_url)
    if product_id is None or country_code is None:
        return None

    api_url = (
        f"https://www.pricerunner.se/{country_code.lower()}/api/"
        f"product-information-edge-rest/public/pricehistory/product/"
        f"{product_id}/{country_code}/DAY"
    )
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "sv-SE,sv;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": "https://www.pricerunner.se/",
    }
    last_error: requests.RequestException | None = None
    response: requests.Response | None = None
    for attempt in range(1, 4):
        try:
            response = requests.get(
                api_url,
                headers=headers,
                params={"selectedInterval": "INFINITE_DAYS", "filter": "NATIONAL"},
                timeout=timeout_s,
            )
            response.raise_for_status()
            break
        except requests.RequestException as exc:
            last_error = exc
            if attempt == 3:
                print(f"[history_summary_error] {product_url} :: {exc}")
                return None
            time.sleep(attempt)

    if response is None:
        if last_error is not None:
            print(f"[history_summary_error] {product_url} :: {last_error}")
        return None

    payload = response.json()
    history = payload.get("history")
    if not isinstance(history, list) or not history:
        print(f"[history_summary_error] {product_url} :: empty history payload")
        return None

    prices = [
        float(point["price"])
        for point in history
        if isinstance(point, dict) and isinstance(point.get("price"), (int, float))
    ]
    if not prices:
        print(f"[history_summary_error] {product_url} :: no numeric prices in history payload")
        return None

    current_price = prices[-1]
    historical_low = payload.get("lowest")
    if not isinstance(historical_low, (int, float)):
        historical_low = min(prices)
    average_price = compute_time_weighted_average_price(history)
    if average_price is None:
        average_price = sum(prices) / len(prices)
    currency_code = str(payload.get("currencyCode") or "SEK")
    return {
        "current_price": format_money_amount(current_price, currency_code),
        "historical_low": format_money_amount(float(historical_low), currency_code),
        "average_price": format_money_amount(
            average_price,
            currency_code,
            round_to_whole=True,
        ),
    }


def build_discount_product_table(rows: list[dict[str, str]]) -> str:
    headers = [
        ("id", "#id"),
        ("discount_percent", "Price drop %"),
        ("current_price", "Current price"),
        ("average_price", "Average price"),
        ("historical_low", "Historical lowest price"),
    ]
    widths = {
        key: max(len(label), *(len(row[key]) for row in rows))
        for key, label in headers
    }

    def render_row(row: dict[str, str]) -> str:
        return " | ".join(
            row[key].ljust(widths[key])
            for key, _ in headers
        )

    header_row = render_row({key: label for key, label in headers})
    divider_row = "-+-".join("-" * widths[key] for key, _ in headers)
    body_rows = [render_row(row) for row in rows]
    return "\n".join([header_row, divider_row, *body_rows])


def build_new_discount_product_rows(
    matches: list[DiscountMatch],
    previous_entry: dict[str, str] | None,
    timeout_s: int,
) -> list[dict[str, str]]:
    previous_keys = parse_discount_match_state_value(
        previous_entry.get("match_state") if previous_entry else None
    )
    rows: list[dict[str, str]] = []
    for match in matches:
        match_key = build_discount_match_state_key(match)
        if match_key in previous_keys or not match.product_url:
            continue
        try:
            summary = fetch_discount_price_summary(match.product_url, timeout_s)
        except requests.RequestException:
            continue
        if summary is None:
            continue
        product_index = len(rows) + 1
        rows.append(
            {
                "id": str(product_index),
                "discount_percent": format_discount_percent(match.discount_percent),
                "current_price": summary["current_price"],
                "average_price": summary["average_price"],
                "historical_low": summary["historical_low"],
            }
        )
    return rows


def build_discount_item_message(
    watch: dict[str, object],
    matches: list[DiscountMatch],
    previous_entry: dict[str, str] | None,
    today_iso: str,
    new_product_rows: list[dict[str, str]] | None = None,
) -> str | None:
    threshold = int(watch["min_discount_percent"])
    previous_status = previous_entry.get("status") if previous_entry else None
    previous_alert_key = previous_entry.get("alert_key") if previous_entry else None

    if not matches:
        if previous_status == "alerting":
            return (
                f"On {today_iso}, {watch['name']} no longer has discounts "
                f"at or above {threshold}%."
            )
        return None

    alert_key = build_discount_alert_key(matches)
    if previous_status == "alerting" and previous_alert_key == alert_key:
        return None

    lines = [
        (
            f"<b>{html.escape(str(watch['name']))}</b>: "
            f"{len(matches)} discounts at or above {threshold}% on {today_iso}."
        )
    ]
    if new_product_rows:
        lines.append("<pre>")
        lines.append(html.escape(build_discount_product_table(new_product_rows)))
        lines.append("</pre>")
    return "\n".join(lines)


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


def print_tagged_message(tag: str, message: str) -> None:
    for line in message.splitlines():
        print(f"[{tag}] {line}")


def print_selector_results(
    url: str,
    html_text: str,
    site_name: str | None,
    selectors: list[dict[str, str]],
) -> str | None:
    soup = BeautifulSoup(html_text, "html.parser")
    print(f"[url] {url}")
    print(f"[site_schema] {site_name or 'N/A'}")
    print("[selector_results]")
    found_any = False
    parsed_price: str | None = None

    for selector_entry in selectors:
        selector_type = selector_entry["type"]
        selector = selector_entry["value"]
        currency_hint = selector_entry.get("currency")
        if selector_type == "css":
            node = soup.select_one(selector)
            if node is None:
                text = None
            elif "attr" in selector_entry:
                attr_value = node.get(selector_entry["attr"])
                text = clean_text(str(attr_value)) if attr_value is not None else None
            else:
                text = clean_text(node.get_text(" ", strip=True))
        else:
            text = try_xpath(html_text, selector)

        price = normalize_price(text, currency_hint) if text else None
        print(f"- {selector_type}: {selector}")
        if "attr" in selector_entry:
            print(f"  attr: {selector_entry['attr']}")
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


def run_price_mode() -> int:
    csv_path = os.getenv("LINKS_CSV_PATH", default_data_path(DEFAULT_LINKS_CSV))
    state_path = os.getenv("PRICE_STATE_PATH", default_data_path(DEFAULT_STATE_PATH))
    selector_schema_path = os.getenv(
        "SELECTOR_SCHEMA_PATH", default_data_path(DEFAULT_SELECTOR_SCHEMA_PATH)
    )
    urls = read_links(csv_path)
    if not urls:
        urls = [os.getenv("FETCH_URL", DEFAULT_URL)]

    timeout_s = int(os.getenv("FETCH_TIMEOUT_SECONDS", "20"))
    today_iso = date.today().isoformat()
    selector_schema = load_selector_schema(selector_schema_path)
    state = load_state(state_path)
    print(f"[links_source] {csv_path}")
    print(f"[links_count] {len(urls)}")
    print(f"[state_path] {state_path}")
    print(f"[selector_schema_path] {selector_schema_path}")

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

        site_name, selectors = get_selectors_for_url(url, selector_schema)
        if not selectors:
            print(f"[url] {url}")
            print("[error] No selector schema matched this URL.")
            failures += 1
            continue

        price = print_selector_results(url, html_text, site_name, selectors)
        if price:
            matches += 1
            message = build_item_message(price, state.get(url), today_iso)
            print_tagged_message("item_message", message)
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


def run_discount_mode() -> int:
    config_path = os.getenv(
        "DISCOUNT_CONFIG_PATH", default_data_path(DEFAULT_DISCOUNT_CONFIG_PATH)
    )
    state_path = os.getenv(
        "DISCOUNT_STATE_PATH", default_data_path(DEFAULT_DISCOUNT_STATE_PATH)
    )
    timeout_s = int(os.getenv("FETCH_TIMEOUT_SECONDS", "20"))
    today_iso = date.today().isoformat()
    config = load_discount_config(config_path)
    watches = normalize_discount_watches(config.get("watches"))
    state = load_state(state_path)
    print(f"[watch_mode] discount")
    print(f"[discount_config_path] {config_path}")
    print(f"[discount_state_path] {state_path}")
    print(f"[watch_count] {len(watches)}")

    if not watches:
        print("[error] No valid discount watches were found in the config.")
        return 1

    matches = 0
    failures = 0
    item_messages: list[str] = []
    updated_state = state.copy()
    for index, watch in enumerate(watches, start=1):
        print(f"\n=== Watch {index}/{len(watches)} ===")
        url = str(watch["url"])
        state_key = build_discount_state_key(watch)
        previous_entry = state.get(state_key)

        try:
            html_text = fetch_html(url, timeout_s)
        except requests.RequestException as exc:
            failures += 1
            print(f"[watch] {watch['name']}")
            print(f"[url] {url}")
            print(f"[error] {exc}")
            print(f"[watch_result] {watch['name']}: request failed")
            continue

        discount_matches = extract_discount_matches(html_text, watch)
        print_discount_watch_results(watch, discount_matches)
        if discount_matches:
            matches += 1

        new_product_rows = build_new_discount_product_rows(
            discount_matches,
            previous_entry,
            timeout_s,
        )
        message = build_discount_item_message(
            watch,
            discount_matches,
            previous_entry,
            today_iso,
            new_product_rows,
        )
        if message:
            print_tagged_message("item_message", message)
            item_messages.append(message)

        updated_state[state_key] = {
            "alert_key": build_discount_alert_key(discount_matches),
            "last_checked": today_iso,
            "last_message": message or "",
            "match_state": build_discount_match_state_value(discount_matches),
            "status": "alerting" if discount_matches else "clear",
        }

    save_state(state_path, updated_state)
    print("\n[summary]")
    print(f"matching_watches: {matches}")
    print(f"failed_watches: {failures}")
    print(f"total_watches: {len(watches)}")
    print(f"item_messages: {len(item_messages)}")
    return 0


def main() -> int:
    watch_mode = os.getenv("WATCH_MODE", DEFAULT_WATCH_MODE).strip().lower()
    if watch_mode in {"discount", "discounts"}:
        return run_discount_mode()
    return run_price_mode()


if __name__ == "__main__":
    sys.exit(main())
