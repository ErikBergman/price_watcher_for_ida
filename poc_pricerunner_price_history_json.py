from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, unquote


DEFAULT_URL = (
    "https://www.pricerunner.se/pl/16-3396392666/Kylfrysar/"
    "LG-Koeleskab-Fryser-363liter-Klasse-E-274liter-Fritstaaende-"
    "Prime-soelv-Rostfritt-Staal-Silver-priser"
)
PRODUCT_ID_RE = re.compile(r"/pl/\d+-(\d+)(?:/|$)")
INITIAL_STATE_RE = re.compile(
    r'<script[^>]+type="application/json"[^>]*>(.*?)</script>',
    re.DOTALL,
)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "PoC: fetch a PriceRunner product page with curl_cffi and extract "
            "price-history rows from the same JSON endpoint the frontend uses."
        )
    )
    parser.add_argument("--url", default=DEFAULT_URL, help="Product page URL.")
    parser.add_argument(
        "--range",
        default="THREE_MONTHS",
        help="selectedInterval value used by the history API.",
    )
    parser.add_argument(
        "--bucket",
        default="DAY",
        help="History bucket used by the history API, for example DAY or HOUR.",
    )
    parser.add_argument(
        "--merchant-id",
        help="Optional merchantId filter for the history API.",
    )
    parser.add_argument(
        "--impersonate",
        default="chrome136",
        help="curl_cffi browser fingerprint to impersonate.",
    )
    parser.add_argument(
        "--timeout-s",
        type=int,
        default=30,
        help="Request timeout in seconds.",
    )
    parser.add_argument(
        "--dump-json",
        type=Path,
        help="Optional path to save the raw API JSON response.",
    )
    return parser.parse_args(argv)


def infer_country_code_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    host_parts = hostname.split(".")
    tld = host_parts[-1] if host_parts else ""
    if len(tld) == 2 and tld.isalpha():
        return tld.upper()

    first_segment = parsed.path.strip("/").split("/", 1)[0]
    if len(first_segment) == 2 and first_segment.isalpha():
        return first_segment.upper()

    return None


def infer_product_id_from_url(url: str) -> str | None:
    match = PRODUCT_ID_RE.search(urlparse(url).path)
    return match.group(1) if match else None


def infer_product_name_from_url(url: str) -> str | None:
    path = urlparse(url).path.rstrip("/")
    slug = path.rsplit("/", 1)[-1]
    if slug.endswith("-priser"):
        slug = slug[: -len("-priser")]
    if slug:
        return unquote(slug).replace("-", " ")
    return None


def extract_initial_state(html: str) -> dict:
    match = INITIAL_STATE_RE.search(html)
    if match is None:
        raise RuntimeError("Could not find initial application/json state in HTML.")
    return json.loads(match.group(1))


def fetch_page_state(*, url: str, impersonate: str, timeout_s: int) -> tuple[dict, str]:
    from curl_cffi import requests

    response = requests.get(
        url,
        impersonate=impersonate,
        timeout=timeout_s,
        headers={
            "accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
            "accept-language": "sv-SE,sv;q=0.9,en-US;q=0.8,en;q=0.7",
            "cache-control": "no-cache",
            "pragma": "no-cache",
        },
    )
    response.raise_for_status()
    return extract_initial_state(response.text), str(response.url)


def extract_product_context(state: dict) -> dict:
    site = state.get("__SITE__", {})
    queries = state.get("__DEHYDRATED_QUERY_STATE__", {}).get("queries", [])
    product_query = next(
        (
            query
            for query in queries
            if query.get("queryKey", [None])[0] == "product-detail-initial"
        ),
        None,
    )
    if product_query is None:
        raise RuntimeError("Could not find product-detail-initial query in dehydrated state.")

    product_data = product_query.get("state", {}).get("data", {})
    product = product_data.get("product", {})
    if not product.get("id"):
        raise RuntimeError("Could not find product id in dehydrated state.")

    return {
        "country_code": site.get("countryCode"),
        "product_id": str(product["id"]),
        "product_name": product.get("name"),
    }


def resolve_product_context(
    *,
    url: str,
    impersonate: str,
    timeout_s: int,
) -> tuple[dict, str]:
    context = {
        "country_code": infer_country_code_from_url(url),
        "product_id": infer_product_id_from_url(url),
        "product_name": infer_product_name_from_url(url),
    }
    if context["country_code"] and context["product_id"]:
        return context, url

    state, page_url = fetch_page_state(
        url=url,
        impersonate=impersonate,
        timeout_s=timeout_s,
    )
    resolved = extract_product_context(state)
    if context["product_name"] and not resolved.get("product_name"):
        resolved["product_name"] = context["product_name"]
    return resolved, page_url


def fetch_price_history(
    *,
    country_code: str,
    product_id: str,
    bucket: str,
    interval: str,
    merchant_id: str | None,
    impersonate: str,
    timeout_s: int,
) -> tuple[dict, str]:
    from curl_cffi import requests

    api_url = (
        f"https://www.pricerunner.se/{country_code.lower()}/api/"
        f"product-information-edge-rest/public/pricehistory/product/"
        f"{product_id}/{country_code}/{bucket}"
    )
    params = {
        "selectedInterval": interval,
        "filter": "NATIONAL",
    }
    if merchant_id:
        params["merchantId"] = merchant_id

    response = requests.get(
        api_url,
        impersonate=impersonate,
        timeout=timeout_s,
        params=params,
        headers={
            "accept": "application/json,text/plain,*/*",
            "accept-language": "sv-SE,sv;q=0.9,en-US;q=0.8,en;q=0.7",
            "referer": "https://www.pricerunner.se/",
        },
    )
    response.raise_for_status()
    return response.json(), response.url


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def format_price(value: float | int | None, currency: str) -> str:
    if value is None:
        return "-"
    amount = f"{value:,.2f}".replace(",", " ").replace(".00", "")
    return f"{amount} {currency}"


def compress_history_rows(history: list[dict]) -> list[dict]:
    if not history:
        return []

    newest_first = list(reversed(history))
    rows: list[dict] = []
    current_price = newest_first[0]["price"]

    for index, point in enumerate(newest_first):
        if point["price"] != current_price:
            previous = dict(newest_first[index - 1])
            previous["newPrice"] = point["price"]
            rows.append(previous)
            current_price = point["price"]

    rows.append(dict(newest_first[-1]))
    return rows


def build_table_rows(history_rows: list[dict], currency: str) -> list[list[str]]:
    body_rows: list[list[str]] = []
    for row in history_rows:
        timestamp = row["timestamp"]
        price = row["price"]
        new_price = row.get("newPrice")
        delta = "-" if new_price is None else format_price(price - new_price, currency)
        body_rows.append(
            [
                parse_timestamp(timestamp).date().isoformat(),
                row.get("merchantName") or "",
                format_price(price, currency),
                delta,
            ]
        )
    return body_rows


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        from curl_cffi import requests  # noqa: F401
    except ImportError:
        print("Install with: pip install curl_cffi")
        return 1

    context, page_url = resolve_product_context(
        url=args.url,
        impersonate=args.impersonate,
        timeout_s=args.timeout_s,
    )
    api_payload, api_url = fetch_price_history(
        country_code=context["country_code"],
        product_id=context["product_id"],
        bucket=args.bucket,
        interval=args.range,
        merchant_id=args.merchant_id,
        impersonate=args.impersonate,
        timeout_s=args.timeout_s,
    )

    if args.dump_json is not None:
        args.dump_json.write_text(
            json.dumps(api_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    history = api_payload.get("history") or []
    table_history = compress_history_rows(history)
    currency = api_payload.get("currencyCode") or "SEK"
    body_rows = build_table_rows(table_history, currency)

    result = {
        "pageUrl": page_url,
        "apiUrl": api_url,
        "productId": context["product_id"],
        "productName": context["product_name"],
        "countryCode": context["country_code"],
        "selectedInterval": args.range,
        "bucket": args.bucket,
        "merchantId": args.merchant_id,
        "historyCount": len(history),
        "rowCount": len(body_rows),
        "headerRows": [["Date", "Store", "Lowest price", "Price change"]],
        "bodyRows": body_rows,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
