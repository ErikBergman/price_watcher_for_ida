# Price Watcher for Ida

This project monitors product pages, extracts prices or discount badges, remembers the last known result, and sends a Telegram message when the GitHub Action runs.

The repository is intended to be reusable. The code lives in GitHub. The changing data lives outside git in one Koofr folder.

## Overview

Price mode uses three runtime files:

- `links.csv`: the product URLs to check
- `site_selectors.json`: the selector rules for each website
- `price_memory.json`: the last known price per URL

Discount mode uses two optional runtime files:

- `discount_watchers.json`: category or listing pages plus discount-threshold rules
- `discount_memory.json`: the last known alert state for each discount watch

Those files should live in one Koofr folder.

Example:

- local Koofr-synced folder on your Mac: `/Users/your-name/Koofr/prices_for_ida`
- matching Koofr path used by GitHub Actions: `My desktop sync/prices_for_ida`

That means:

- local runs read and write the files in your Koofr-synced folder
- GitHub Actions downloads those same files from Koofr
- after a workflow run, the updated memory file is uploaded back to Koofr

## What The Project Does

In the default price mode, for each URL in `links.csv`, [watch_price.py](/Users/erikbergman/Documents/Programmering/Pythonprojekt/price_watcher_for_ida/price_watcher_for_ida/watch_price.py):

1. downloads the product page
2. finds the matching site definition in `site_selectors.json`
3. tries that site's selectors in order
4. extracts the first valid price
5. compares it with the previous value in `price_memory.json`
6. prints one item message

The item message is one of these:

- first time seen: `Current price: 235 kr`
- unchanged: `The item remains at 235 kr.`
- changed: `On 2026-03-14, the item's price decreased from 299 kr to 235 kr.`

In `WATCH_MODE=discount`, the script instead:

1. loads watches from `discount_watchers.json`
2. fetches each category or listing page
3. extracts discount badges within configured item containers
4. keeps only discounts at or above `min_discount_percent`
5. remembers whether the alert set changed in `discount_memory.json`
6. prints an item message only when a discount alert appears, changes, or clears

The GitHub Actions workflow currently defaults to `WATCH_MODE=discount` unless you override it with a repository variable.

The current fridge setup runs in discount mode against:

- `https://www.pricerunner.se/cl/16/Kylfrysar?sort=price_drop`

## Requirements

You need:

- a GitHub repository with Actions enabled
- a Koofr account
- a Koofr app-specific password
- a Telegram bot token from BotFather
- a Telegram chat ID

For local usage you also need:

- Python 3.12 or later
- the dependencies in [requirements.txt](/Users/erikbergman/Documents/Programmering/Pythonprojekt/price_watcher_for_ida/price_watcher_for_ida/requirements.txt)

## Setup Order

If you are starting from scratch, do it in this order:

1. Create the Koofr folder
2. Put the runtime files for the mode you want in that folder
3. Set up Telegram
4. Add GitHub Secrets
5. Run the workflow manually once
6. Let the schedule handle the rest

## 1. Koofr Setup

### Create a Koofr folder

Create one folder in Koofr for this project's runtime files.

Example:

- local sync path on your Mac: `/Users/your-name/Koofr/prices_for_ida`
- Koofr path for GitHub Secrets: `My desktop sync/prices_for_ida`

Important:

- do not use your local macOS path as `KOOFR_PATH`
- use the Koofr-visible path, for example `My desktop sync/prices_for_ida`

### Create a Koofr app-specific password

Use Koofr's application password feature. Do not use your normal Koofr account password in GitHub Secrets.

You will need:

- your Koofr email address
- your Koofr app-specific password
- your Koofr folder path, for example `My desktop sync/prices_for_ida`

### Put the runtime files for your chosen mode in the Koofr folder

For price mode, add:

- `links.csv`
- `site_selectors.json`

For discount mode, add:

- `discount_watchers.json`

Example content:

```csv
"https://www.cervera.se/produkt/arabia-tuokio-skal-16-cm-koboltbla",
```

Notes:

- one or more URLs can be stored in `links.csv`
- the script reads every CSV cell and keeps values that start with `http://` or `https://`

Example `discount_watchers.json`:

```json
{
  "watches": [
    {
      "name": "PriceRunner Kylfrysar",
      "url": "https://www.pricerunner.se/cl/16/Kylfrysar?sort=price_drop",
      "item_selector": "div.pr-ugbjc3",
      "discount_selector": "div.pr-nkf7ss",
      "title_selector": "h2",
      "title_attr": "title",
      "min_discount_percent": 40,
      "max_items": 12
    }
  ]
}
```

### The memory file does not need to exist yet

The workflow creates the mode-specific memory file automatically on the first successful run if it does not already exist.

That means:

- price mode creates `price_memory.json`
- discount mode creates `discount_memory.json`

## 2. Local Python Setup

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 3. Make Local Runs Use Koofr Automatically

If you want local commands to use the Koofr-synced folder automatically, set:

```bash
export PRICE_WATCHER_DATA_DIR=~/Koofr/prices_for_ida
```

After that, the scripts will use:

- `~/Koofr/prices_for_ida/links.csv`
- `~/Koofr/prices_for_ida/site_selectors.json`
- `~/Koofr/prices_for_ida/price_memory.json`
- `~/Koofr/prices_for_ida/discount_watchers.json`
- `~/Koofr/prices_for_ida/discount_memory.json`

This is the simplest local setup because you do not need to pass file paths manually.

If you want this to be permanent in Terminal, add the same line to your `~/.zshrc`.

### Important note about where files are saved

The scripts only use the Koofr folder automatically if `PRICE_WATCHER_DATA_DIR` is set in the process that starts them.

That means:

- a plain Terminal run without the environment variable saves to local `data/`
- a configured debugger or task can save to Koofr
- the startup output in `discover_selectors.py` shows the exact schema path before saving

## 4. Add Or Discover Site Selectors

This project uses [discover_selectors.py](/Users/erikbergman/Documents/Programmering/Pythonprojekt/price_watcher_for_ida/price_watcher_for_ida/discover_selectors.py) to help create `site_selectors.json`.

You can run it with a URL:

```bash
python discover_selectors.py "https://example.com/product-page"
```

Or without a URL:

```bash
python discover_selectors.py
```

If the URL is omitted, the script prompts for one.

The helper:

1. fetches the page
2. finds price-like candidates in the server-rendered HTML
3. shows up to three candidates
4. asks whether a candidate looks correct
5. saves the selected site entry into `site_selectors.json`

If no candidate is confirmed, nothing is saved.

### What the helper is good at

It works best when the price exists in the HTML returned by the server, for example:

- visible text such as `235 kr`
- meta tags such as `content="4743.75"`
- attributes such as `data-price="9938"`

It is less reliable for sites that build the price only after JavaScript runs in the browser.

### What gets saved

The helper saves one site definition containing:

- the site name
- matching domains
- the confirmed selector
- fallback selectors for the same price when available

### Example `site_selectors.json`

```json
{
  "sites": [
    {
      "name": "cervera",
      "domains": ["cervera.se", "www.cervera.se"],
      "selectors": [
        {
          "type": "css",
          "value": ".ProductInfoBlock_pdpPrice__eB8Io > span:nth-child(1)"
        },
        {
          "type": "css",
          "value": "span.ProductPrice_price___B9X_.ProductInfoBlock_pdpPrice__eB8Io.ProductInfoBlock_pdpSalePrice__6qtS6 span"
        },
        {
          "type": "xpath",
          "value": "/html/body/div[2]/main/section/div/div[3]/div[1]/div/div[1]/span[1]/span"
        }
      ]
    }
  ]
}
```

Schema notes:

- `sites` is a list of site definitions
- `domains` is used to match the URL hostname
- `selectors` is tried in order
- each selector needs:
  - `type`: `css` or `xpath`
  - `value`: the selector string
- optional selector fields:
  - `attr`: read from an attribute instead of element text
  - `currency`: append a currency hint such as `kr` when the raw value is numeric only
- optional site field:
  - `url_contains`: use this when one domain needs different selector sets for different kinds of URLs

You can use [example.site_selectors.json](/Users/erikbergman/Documents/Programmering/Pythonprojekt/price_watcher_for_ida/price_watcher_for_ida/data/example.site_selectors.json) as a starting point.

## 5. Telegram Setup

### Create a bot with BotFather

Use BotFather in Telegram to create a bot and copy the bot token.

### Start a chat with the bot

Open the bot in Telegram and send it at least one message.

### Find your chat ID

Run:

```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates"
```

Look for `message.chat.id`.

Examples:

- private chat: `123456789`
- group chat: `-1001234567890`

## 6. GitHub Setup

### Push the repository to GitHub

The workflow file must exist on the default branch if the schedule is going to work.

### Add GitHub Actions secrets

In GitHub:

`Settings` -> `Secrets and variables` -> `Actions`

Add these repository secrets:

- `KOOFR_EMAIL`
- `KOOFR_APP_PASSWORD`
- `KOOFR_PATH`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Example:

```text
KOOFR_EMAIL=your@email.com
KOOFR_APP_PASSWORD=your-koofr-app-password
KOOFR_PATH=My desktop sync/prices_for_ida
```

### Current schedule

The workflow in [price-watcher.yml](/Users/erikbergman/Documents/Programmering/Pythonprojekt/price_watcher_for_ida/price_watcher_for_ida/.github/workflows/price-watcher.yml) currently contains:

```yaml
on:
  push:
    branches:
      - main
  workflow_dispatch:
    inputs:
      watch_mode:
        default: discount
  schedule:
    - cron: "0 19 * * *"
```

GitHub cron uses UTC.

That means the workflow is scheduled for:

- `19:00 UTC`
- `20:00 CET`
- `21:00 CEST`

As of April 6, 2026, Sweden is on daylight saving time, so the current schedule runs at `21:00` Swedish time.

## 7. Run It Manually Once

Before relying on the schedule:

1. open `Actions`
2. open `Price Watcher`
3. click `Run workflow`
4. leave `watch_mode=discount` for the fridge watcher unless you intentionally want price mode

The workflow also runs automatically once when you push setup or watcher changes to `main`, and then continues on the daily schedule.

This first run confirms:

- GitHub can authenticate to Koofr
- the runtime files for the selected mode are found
- the correct memory file is created or updated
- Telegram is configured correctly

## Local Usage

### Run the watcher locally

```bash
python watch_price.py
```

If `PRICE_WATCHER_DATA_DIR` is set, it uses the Koofr-synced files. Otherwise it uses local `data/`.

### Run discount-threshold mode locally

```bash
WATCH_MODE=discount \
DISCOUNT_CONFIG_PATH=data/example.discount_watchers.json \
python watch_price.py
```

Useful discount-mode environment variables:

- `WATCH_MODE`
- `DISCOUNT_CONFIG_PATH`
- `DISCOUNT_STATE_PATH`
- `FETCH_TIMEOUT_SECONDS`

### Current GitHub Actions default

Manual and scheduled workflow runs now default to `WATCH_MODE=discount`.

You can still override this:

- in the GitHub Actions UI with the `watch_mode` input on manual runs
- with a repository variable `WATCH_MODE=price` if you want to switch the scheduled run back temporarily

### Override individual paths manually

You can override any file path explicitly:

- `LINKS_CSV_PATH`
- `SELECTOR_SCHEMA_PATH`
- `PRICE_STATE_PATH`
- `FETCH_TIMEOUT_SECONDS`
- `FETCH_URL`

Example:

```bash
LINKS_CSV_PATH=runtime_data/links.csv \
SELECTOR_SCHEMA_PATH=runtime_data/site_selectors.json \
PRICE_STATE_PATH=runtime_data/price_memory.json \
python watch_price.py
```

### Example beginner workflow

```bash
source .venv/bin/activate
export PRICE_WATCHER_DATA_DIR=~/Koofr/prices_for_ida
python discover_selectors.py "https://www.ajprodukter.se/p/mysgrop-159471-65877"
python watch_price.py
```

What happens here:

- the helper saves the selector schema into your Koofr-synced folder
- the watcher reads `links.csv` from that same folder
- the watcher updates `price_memory.json` in that same folder
- GitHub Actions can later use those same files through Koofr

## What Happens During A Workflow Run

The workflow in [price-watcher.yml](/Users/erikbergman/Documents/Programmering/Pythonprojekt/price_watcher_for_ida/price_watcher_for_ida/.github/workflows/price-watcher.yml):

1. checks out the repository
2. installs Python dependencies
3. installs `rclone`
4. configures a Koofr remote from GitHub Secrets
5. downloads the runtime files for the selected watch mode into `runtime_data/`
6. runs [watch_price.py](/Users/erikbergman/Documents/Programmering/Pythonprojekt/price_watcher_for_ida/price_watcher_for_ida/watch_price.py)
7. uploads the updated mode-specific memory file back to Koofr
8. extracts the item message from the script output
9. sends a Telegram message

In discount mode:

- it reads `discount_watchers.json`
- it writes `discount_memory.json`
- if `discount_watchers.json` is missing in Koofr, it falls back to the tracked [example.discount_watchers.json](/Users/erikbergman/Documents/Programmering/Pythonprojekt/price_watcher_for_ida/price_watcher_for_ida/data/example.discount_watchers.json)

## Memory File Format

`price_memory.json` stores the last known price for each monitored URL.

Example:

```json
{
  "https://www.cervera.se/produkt/arabia-tuokio-skal-16-cm-koboltbla": {
    "last_checked": "2026-03-14",
    "last_message": "Current price: 235 kr",
    "price": "235 kr"
  }
}
```

The watcher uses this file to determine whether an item is:

- new
- unchanged
- increased
- decreased

In discount mode, `discount_memory.json` stores the last alert state for each configured watch.

Example:

```json
{
  "PriceRunner Kylfrysar|https://www.pricerunner.se/cl/16/Kylfrysar?sort=price_drop|40": {
    "alert_key": "48|LG Example",
    "last_checked": "2026-04-06",
    "last_message": "PriceRunner Kylfrysar: 1 discounts at or above 40% on 2026-04-06.",
    "status": "alerting"
  }
}
```

## Repository Files

- [watch_price.py](/Users/erikbergman/Documents/Programmering/Pythonprojekt/price_watcher_for_ida/price_watcher_for_ida/watch_price.py): fetches pages, parses prices, and manages memory
- [discover_selectors.py](/Users/erikbergman/Documents/Programmering/Pythonprojekt/price_watcher_for_ida/price_watcher_for_ida/discover_selectors.py): interactive helper for building selector rules
- [price-watcher.yml](/Users/erikbergman/Documents/Programmering/Pythonprojekt/price_watcher_for_ida/price_watcher_for_ida/.github/workflows/price-watcher.yml): GitHub Actions workflow
- [requirements.txt](/Users/erikbergman/Documents/Programmering/Pythonprojekt/price_watcher_for_ida/price_watcher_for_ida/requirements.txt): Python dependencies
- [example.links.csv](/Users/erikbergman/Documents/Programmering/Pythonprojekt/price_watcher_for_ida/price_watcher_for_ida/data/example.links.csv): example URL list
- [example.site_selectors.json](/Users/erikbergman/Documents/Programmering/Pythonprojekt/price_watcher_for_ida/price_watcher_for_ida/data/example.site_selectors.json): example selector schema
- [example.discount_watchers.json](/Users/erikbergman/Documents/Programmering/Pythonprojekt/price_watcher_for_ida/price_watcher_for_ida/data/example.discount_watchers.json): example discount-watch config

## VS Code Notes

The tracked [launch.json](/Users/erikbergman/Documents/Programmering/Pythonprojekt/price_watcher_for_ida/price_watcher_for_ida/.vscode/launch.json) is intentionally generic so the repository can be reused on other machines.

Machine-specific VS Code files such as:

- `.vscode/settings.json`
- `.vscode/tasks.json`

should stay local and are ignored by git.

If you want VS Code to use your Koofr folder automatically, configure that locally on your own machine rather than committing your absolute path.

## Troubleshooting

### Koofr: `401`

Authentication failed.

Check:

- `KOOFR_EMAIL` is correct
- `KOOFR_APP_PASSWORD` is a Koofr app-specific password
- you did not use your normal Koofr password

### Koofr: `directory not found`

This usually means `KOOFR_PATH` is wrong.

Use the Koofr-visible path, not your local disk path.

Example:

- wrong: `/Users/your-name/Koofr/prices_for_ida`
- right: `My desktop sync/prices_for_ida`

### No selector schema matched this URL

The URL hostname did not match any site definition in `site_selectors.json`.

Check:

- the actual domain in the URL
- the `domains` list in the schema
- any `url_contains` rule on that site definition

### `site_selectors.json` was saved to local `data/` instead of Koofr

This means the process that started `discover_selectors.py` did not have `PRICE_WATCHER_DATA_DIR` set.

Check the startup panel in the helper. It prints the active schema path before saving.

### Telegram message does not arrive

Check:

- the bot token is correct
- the chat ID is correct
- you already sent at least one message to the bot

### Scheduled run does not happen exactly on time

GitHub scheduled workflows are not real-time. Delays of several minutes are normal.

Also check:

- the workflow file is on the default branch
- the workflow is enabled
- the repository has not been inactive long enough for scheduled workflows to be disabled

## Notes

- The current workflow still contains a temporary `Debug Koofr paths` step. It is useful during setup but can be removed once Koofr access is stable.
