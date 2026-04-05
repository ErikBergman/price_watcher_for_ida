from __future__ import annotations

from pathlib import Path

import discover_selectors


def test_collect_candidates_finds_text_and_attribute_prices() -> None:
    html = """
    <html>
      <head>
        <meta property="product:price:currency" content="SEK">
        <meta property="product:price:amount" content="4743.75">
      </head>
      <body>
        <span class="visible-price">235 kr</span>
        <div id="product" data-price="9938"></div>
      </body>
    </html>
    """

    candidates = discover_selectors.collect_candidates(html)
    parsed_prices = {candidate.parsed_price for candidate in candidates}
    sources = {candidate.source for candidate in candidates}

    assert "235 kr" in parsed_prices
    assert "4 743.75 kr" in parsed_prices
    assert "9 938 kr" in parsed_prices
    assert "text" in sources
    assert "attr:content" in sources
    assert "attr:data-price" in sources


def test_discover_saves_schema_after_confirmation(monkeypatch, tmp_path: Path) -> None:
    schema_path = tmp_path / "site_selectors.json"
    candidate = discover_selectors.Candidate(
        source="text",
        text="235 kr",
        parsed_price="235 kr",
        css_selector=".price",
        xpath_selector="/html/body/span",
        attr=None,
        currency=None,
        score=(0, 1, -6),
    )
    monkeypatch.setattr(discover_selectors, "fetch_html", lambda url, timeout_s: "<html></html>")
    monkeypatch.setattr(discover_selectors, "collect_candidates", lambda html: [candidate])
    monkeypatch.setattr(discover_selectors, "prompt_yes_no", lambda prompt: True)

    exit_code = discover_selectors.discover("https://example.com/product", schema_path, 20)
    saved = discover_selectors.load_schema(schema_path)

    assert exit_code == 0
    assert saved["sites"][0]["domains"] == ["example.com", "www.example.com"]
    assert saved["sites"][0]["selectors"][0]["value"] == ".price"


def test_discover_stops_after_three_rejections(monkeypatch, tmp_path: Path) -> None:
    schema_path = tmp_path / "site_selectors.json"
    prompts: list[str] = []

    candidates = [
        discover_selectors.Candidate(
            source="text",
            text=f"{index}00 kr",
            parsed_price=f"{index}00 kr",
            css_selector=f".price-{index}",
            xpath_selector=f"/html/body/span[{index}]",
            attr=None,
            currency=None,
            score=(0, 1, -6),
        )
        for index in range(1, 5)
    ]

    monkeypatch.setattr(discover_selectors, "fetch_html", lambda url, timeout_s: "<html></html>")
    monkeypatch.setattr(discover_selectors, "collect_candidates", lambda html: candidates)
    monkeypatch.setattr(
        discover_selectors,
        "prompt_yes_no",
        lambda prompt: prompts.append(prompt) or False,
    )

    exit_code = discover_selectors.discover("https://example.com/product", schema_path, 20)

    assert exit_code == 1
    assert len(prompts) == 3
    assert not schema_path.exists()


def test_main_returns_error_when_prompted_url_is_blank(monkeypatch, capsys: object) -> None:
    monkeypatch.setattr(discover_selectors.Prompt, "ask", lambda prompt: "   ")

    exit_code = discover_selectors.main([])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "A URL is required." in output


def test_upsert_site_replaces_existing_domains() -> None:
    schema = {
        "sites": [
            {
                "name": "old",
                "domains": ["example.com", "www.example.com"],
                "selectors": [{"type": "css", "value": ".old"}],
            }
        ]
    }
    replacement = {
        "name": "new",
        "domains": ["example.com", "www.example.com"],
        "selectors": [{"type": "css", "value": ".new"}],
    }

    discover_selectors.upsert_site(schema, replacement)

    assert schema["sites"] == [replacement]
