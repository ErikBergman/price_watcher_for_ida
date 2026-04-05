from __future__ import annotations

import json
from pathlib import Path

import watch_price


def test_default_data_path_uses_repo_data_dir_when_env_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(watch_price.DEFAULT_DATA_DIR_ENV, raising=False)

    path = watch_price.default_data_path("links.csv")

    assert path == str(Path("data") / "links.csv")


def test_default_data_path_uses_configured_data_dir(monkeypatch, tmp_path: Path) -> None:
    koofr_dir = tmp_path / "koofr"
    monkeypatch.setenv(watch_price.DEFAULT_DATA_DIR_ENV, str(koofr_dir))

    path = watch_price.default_data_path("site_selectors.json")

    assert path == str(koofr_dir / "site_selectors.json")


def test_save_and_load_state_in_repo_data_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(watch_price.DEFAULT_DATA_DIR_ENV, raising=False)
    state_path = watch_price.default_data_path("price_memory.json")
    state = {
        "https://example.com/product": {
            "last_checked": "2026-03-15",
            "last_message": "Current price: 235 kr",
            "price": "235 kr",
        }
    }

    watch_price.save_state(state_path, state)
    loaded = watch_price.load_state(state_path)

    assert loaded == state


def test_save_and_load_state_in_configured_data_dir(monkeypatch, tmp_path: Path) -> None:
    koofr_dir = tmp_path / "koofr"
    monkeypatch.setenv(watch_price.DEFAULT_DATA_DIR_ENV, str(koofr_dir))
    state_path = watch_price.default_data_path("price_memory.json")
    state = {
        "https://example.com/product": {
            "last_checked": "2026-03-15",
            "last_message": "The item remains at 235 kr.",
            "price": "235 kr",
        }
    }

    watch_price.save_state(state_path, state)
    loaded = watch_price.load_state(state_path)

    assert loaded == state


def test_read_links_from_repo_data_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(watch_price.DEFAULT_DATA_DIR_ENV, raising=False)
    csv_path = Path(watch_price.default_data_path("links.csv"))
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text(
        "\"https://example.com/a\",not-a-url\nhttps://example.com/b,'https://example.com/c'\n",
        encoding="utf-8",
    )

    links = watch_price.read_links(str(csv_path))

    assert links == [
        "https://example.com/a",
        "https://example.com/b",
        "https://example.com/c",
    ]


def test_read_links_from_configured_data_dir(monkeypatch, tmp_path: Path) -> None:
    koofr_dir = tmp_path / "koofr"
    monkeypatch.setenv(watch_price.DEFAULT_DATA_DIR_ENV, str(koofr_dir))
    csv_path = Path(watch_price.default_data_path("links.csv"))
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text("https://example.com/koofr\n", encoding="utf-8")

    links = watch_price.read_links(str(csv_path))

    assert links == ["https://example.com/koofr"]


def test_load_selector_schema_returns_default_when_missing(tmp_path: Path) -> None:
    schema = watch_price.load_selector_schema(str(tmp_path / "missing.json"))

    assert schema == watch_price.DEFAULT_SELECTOR_SCHEMA


def test_load_discount_config_returns_default_when_missing(tmp_path: Path) -> None:
    config = watch_price.load_discount_config(str(tmp_path / "missing.json"))

    assert config == watch_price.DEFAULT_DISCOUNT_CONFIG


def test_get_selectors_for_url_matches_domain_and_url_contains() -> None:
    schema = {
        "sites": [
            {
                "name": "shop",
                "domains": ["example.com"],
                "url_contains": ["/product/"],
                "selectors": [{"type": "css", "value": ".price"}],
            }
        ]
    }

    site_name, selectors = watch_price.get_selectors_for_url(
        "https://www.example.com/product/123", schema
    )

    assert site_name == "shop"
    assert selectors == [{"type": "css", "value": ".price"}]


def test_print_selector_results_supports_attr_based_selector(capsys: object) -> None:
    html = """
    <html>
      <head><meta property="product:price:currency" content="SEK"></head>
      <body><span id="product" data-price="9938"></span></body>
    </html>
    """

    price = watch_price.print_selector_results(
        "https://example.com/product",
        html,
        "example",
        [{"type": "css", "value": "span#product", "attr": "data-price", "currency": "kr"}],
    )
    output = capsys.readouterr().out

    assert price == "9 938 kr"
    assert "parsed_price: 9 938 kr" in output


def test_extract_discount_matches_filters_by_threshold() -> None:
    html = """
    <html>
      <body>
        <div class="card">
          <div class="badge">-48%</div>
          <h2 title="LG Combo">LG Combo</h2>
        </div>
        <div class="card">
          <div class="badge">-39%</div>
          <h2 title="Samsung Combo">Samsung Combo</h2>
        </div>
      </body>
    </html>
    """

    matches = watch_price.extract_discount_matches(
        html,
        {
            "name": "discount-watch",
            "url": "https://example.com/category",
            "item_selector": ".card",
            "discount_selector": ".badge",
            "title_selector": "h2",
            "title_attr": "title",
            "min_discount_percent": 40,
        },
    )

    assert matches == [watch_price.DiscountMatch(title="LG Combo", discount_percent=48)]


def test_build_discount_item_message_handles_new_same_and_resolved_alerts() -> None:
    watch = {
        "name": "PriceRunner Kylfrysar",
        "url": "https://example.com/category",
        "item_selector": ".card",
        "discount_selector": ".badge",
        "min_discount_percent": 40,
    }
    matches = [watch_price.DiscountMatch(title="LG Combo", discount_percent=48)]
    alert_key = watch_price.build_discount_alert_key(matches)

    new_message = watch_price.build_discount_item_message(watch, matches, None, "2026-04-05")
    same_message = watch_price.build_discount_item_message(
        watch,
        matches,
        {"status": "alerting", "alert_key": alert_key},
        "2026-04-05",
    )
    resolved_message = watch_price.build_discount_item_message(
        watch,
        [],
        {"status": "alerting", "alert_key": alert_key},
        "2026-04-05",
    )

    assert "1 discounts at or above 40%" in (new_message or "")
    assert same_message is None
    assert resolved_message == (
        "On 2026-04-05, PriceRunner Kylfrysar no longer has discounts at or above 40%."
    )


def test_build_item_message_covers_new_same_and_changed_states() -> None:
    new_message = watch_price.build_item_message("235 kr", None, "2026-03-15")
    same_message = watch_price.build_item_message(
        "235 kr",
        {"price": "235 kr"},
        "2026-03-15",
    )
    changed_message = watch_price.build_item_message(
        "199 kr",
        {"price": "235 kr"},
        "2026-03-15",
    )

    assert new_message == "Current price: 235 kr"
    assert same_message == "The item remains at 235 kr."
    assert changed_message == "On 2026-03-15, the item's price decreased from 235 kr to 199 kr."


def test_main_reads_repo_data_and_updates_state(monkeypatch, tmp_path: Path, capsys: object) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(watch_price.DEFAULT_DATA_DIR_ENV, raising=False)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "links.csv").write_text("https://example.com/product\n", encoding="utf-8")
    (data_dir / "site_selectors.json").write_text(
        json.dumps(
            {
                "sites": [
                    {
                        "name": "example",
                        "domains": ["example.com"],
                        "selectors": [{"type": "css", "value": ".price"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        watch_price,
        "fetch_html",
        lambda url, timeout_s: '<html><body><span class="price">235 kr</span></body></html>',
    )

    exit_code = watch_price.main()
    saved_state = watch_price.load_state(str(data_dir / "price_memory.json"))
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Current price: 235 kr" in output
    assert saved_state["https://example.com/product"]["price"] == "235 kr"


def test_main_discount_mode_reads_config_and_updates_state(
    monkeypatch,
    tmp_path: Path,
    capsys: object,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WATCH_MODE", "discount")
    monkeypatch.delenv(watch_price.DEFAULT_DATA_DIR_ENV, raising=False)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "discount_watchers.json").write_text(
        json.dumps(
            {
                "watches": [
                    {
                        "name": "PriceRunner Kylfrysar",
                        "url": "https://example.com/category",
                        "item_selector": ".card",
                        "discount_selector": ".badge",
                        "title_selector": "h2",
                        "title_attr": "title",
                        "min_discount_percent": 40,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        watch_price,
        "fetch_html",
        lambda url, timeout_s: (
            "<html><body>"
            '<div class="card"><div class="badge">-48%</div><h2 title="LG Combo">LG Combo</h2></div>'
            "</body></html>"
        ),
    )

    exit_code = watch_price.main()
    saved_state = watch_price.load_state(str(data_dir / "discount_memory.json"))
    output = capsys.readouterr().out

    state_key = (
        "PriceRunner Kylfrysar|https://example.com/category|40"
    )
    assert exit_code == 0
    assert "PriceRunner Kylfrysar: 1 discounts at or above 40%" in output
    assert saved_state[state_key]["status"] == "alerting"
