from __future__ import annotations

import pytest

import discover_selectors
import watch_price


LIVE_URLS = [
    "https://www.ajprodukter.se/p/mysgrop-159471-65877",
    "https://www.willys.se/produkt/Lok-Gul-Klass-1-100269139_KG",
    "https://cdon.se/produkt/apple-iphone-17-256gb-salviagron-b13ee79fda655df3/",
]


@pytest.mark.live
@pytest.mark.parametrize("url", LIVE_URLS)
def test_fetch_html_live_pages(url: str) -> None:
    html = watch_price.fetch_html(url, timeout_s=20)

    assert "<html" in html.lower()
    assert len(html) > 1000


@pytest.mark.live
@pytest.mark.parametrize(
    ("url", "expected_price"),
    [
        ("https://www.ajprodukter.se/p/mysgrop-159471-65877", "4 743.75 kr"),
        ("https://cdon.se/produkt/apple-iphone-17-256gb-salviagron-b13ee79fda655df3/", "9 938 kr"),
    ],
)
def test_discovery_finds_known_live_prices(url: str, expected_price: str) -> None:
    html = watch_price.fetch_html(url, timeout_s=20)
    candidates = discover_selectors.collect_candidates(html)

    assert any(candidate.parsed_price == expected_price for candidate in candidates)
