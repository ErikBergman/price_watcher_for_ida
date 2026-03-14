# Price Watcher for Ida

This project checks product pages, extracts prices, remembers the last known price for each item, and sends a Telegram notification when the GitHub Action runs.

The repository is designed to be reusable. Runtime data is not stored in git. Instead:

- input data lives in Koofr as `links.csv`
- selector rules live in Koofr as `site_selectors.json`
- memory lives in Koofr as `price_memory.json`
- GitHub Actions downloads both files at the start of a run
- the script updates `price_memory.json`
- GitHub Actions uploads the updated memory file back to Koofr

## What the Script Does

For each URL in `links.csv`, the script:

1. downloads the product page
2. finds the matching site schema in `site_selectors.json`
3. tries that site's configured selectors
3. extracts the first valid `parsed_price`
4. compares that price with the previous stored price
5. prints one of these item messages:

- first time seen: `Current price: 235 kr`
- unchanged: `The item remains at 235 kr.`
- changed: `On 2026-03-14, the item's price decreased from 299 kr to 235 kr.`

## Requirements

You need the following:

- a GitHub repository with Actions enabled
- a Koofr account
- a Koofr app-specific password
- a Telegram bot token from BotFather
- a Telegram chat ID where the bot can send messages

For local testing you also need:

- Python 3.12 or later
- the dependencies in `requirements.txt`

## Repository Files

- [watch_price.py](/Users/erikbergman/Documents/Programmering/Pythonprojekt/price_watcher_for_ida/price_watcher_for_ida/watch_price.py): the scraper and price-memory logic
- [price-watcher.yml](/Users/erikbergman/Documents/Programmering/Pythonprojekt/price_watcher_for_ida/price_watcher_for_ida/.github/workflows/price-watcher.yml): the GitHub Actions workflow
- [requirements.txt](/Users/erikbergman/Documents/Programmering/Pythonprojekt/price_watcher_for_ida/price_watcher_for_ida/requirements.txt): Python dependencies
- [example.links.csv](/Users/erikbergman/Documents/Programmering/Pythonprojekt/price_watcher_for_ida/price_watcher_for_ida/data/example.links.csv): example input file
- [example.site_selectors.json](/Users/erikbergman/Documents/Programmering/Pythonprojekt/price_watcher_for_ida/price_watcher_for_ida/data/example.site_selectors.json): example selector schema
- [.gitignore](/Users/erikbergman/Documents/Programmering/Pythonprojekt/price_watcher_for_ida/price_watcher_for_ida/.gitignore): ignores local runtime data such as `data/links.csv` and `data/price_memory.json`

## Koofr Setup

### 1. Create a folder in Koofr

Create a folder where this project will store its runtime files.

Example:

- local sync path on your Mac: `/Users/erikbergman/Koofr/prices_for_ida`
- Koofr path used by GitHub Actions: `My desktop sync/prices_for_ida`

Important:

- do not use your local macOS path as `KOOFR_PATH`
- use the Koofr-visible path, such as `My desktop sync/prices_for_ida`

### 2. Add `links.csv`

Inside that Koofr folder, create `links.csv`.

Example content:

```csv
"https://www.cervera.se/produkt/arabia-tuokio-skal-16-cm-koboltbla",
```

Notes:

- one or more URLs can be stored in the file
- the script reads every cell in the CSV and keeps values that start with `http://` or `https://`

### 3. Do not create `price_memory.json` manually unless you want to

The workflow creates `price_memory.json` automatically on the first successful run if it does not already exist.

### 4. Add `site_selectors.json`

Inside the same Koofr folder, create `site_selectors.json`.

This file tells the script which selectors to use for each website. The schema is based on domain matching and supports any number of sites.

Example:

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
- `name` is optional but useful in logs
- `domains` is required and matches the URL hostname
- `selectors` is required
- each selector must have:
  - `type`: `css` or `xpath`
  - `value`: the selector string
- optional: `url_contains`
  - use this if one domain needs different selector sets for different URL patterns

Example with two different sites:

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
        }
      ]
    },
    {
      "name": "example-shop",
      "domains": ["example.com", "www.example.com"],
      "selectors": [
        {
          "type": "css",
          "value": ".product-price"
        }
      ]
    }
  ]
}
```

### 5. Create a Koofr app-specific password

Use Koofr's application password feature. Do not use your normal Koofr account password in GitHub Secrets.

You will use:

- your Koofr email address
- your Koofr app password
- your Koofr folder path, for example `My desktop sync/prices_for_ida`

## Telegram Setup

### 1. Create a bot with BotFather

Use BotFather in Telegram to create a bot and copy the bot token.

### 2. Start a chat with the bot

Open the bot in Telegram and send it at least one message. If you do not do this, the bot may not be able to message you.

### 3. Find your chat ID

Run:

```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates"
```

Look for `message.chat.id`.

Examples:

- private chat: `123456789`
- group chat: `-1001234567890`

## GitHub Setup

### 1. Push the repository to GitHub

The workflow file must be on the default branch if you want the schedule trigger to work.

### 2. Add GitHub Actions secrets

In GitHub:

`Settings` -> `Secrets and variables` -> `Actions`

Create these repository secrets:

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

### 3. Check the workflow schedule

The workflow file currently contains:

```yaml
on:
  workflow_dispatch:
  schedule:
    - cron: "41 20 * * *"
```

GitHub cron uses UTC.

That means the action runs every day at:

- `20:41 UTC`
- `21:41 CET` when Sweden is on standard time
- `22:41 CEST` when Sweden is on daylight saving time

### 4. Run it manually once

Before relying on the daily schedule, run it manually:

1. open `Actions`
2. open `Price Watcher`
3. click `Run workflow`

This first run is important because it confirms:

- GitHub can access Koofr
- `links.csv` is found
- `site_selectors.json` is found
- Telegram is configured correctly
- `price_memory.json` gets created or updated

## What Happens During a Workflow Run

The GitHub Action does this:

1. checks out the repository
2. installs `rclone`
3. configures a Koofr remote from GitHub Secrets
4. downloads `links.csv`, `site_selectors.json`, and `price_memory.json` into `runtime_data/`
5. runs [watch_price.py](/Users/erikbergman/Documents/Programmering/Pythonprojekt/price_watcher_for_ida/price_watcher_for_ida/watch_price.py)
6. uploads the updated `price_memory.json` back to Koofr
7. extracts the item message from the script output
8. sends a Telegram message with the result

## Local Development

You can also run the script locally without GitHub Actions.

### 1. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Create local runtime files

The repository ignores these files locally:

- `data/links.csv`
- `data/site_selectors.json`
- `data/price_memory.json`

You can create them yourself for local testing.

Example:

```bash
cp data/example.links.csv data/links.csv
cp data/example.site_selectors.json data/site_selectors.json
printf '{}\n' > data/price_memory.json
```

### 3. Run the script

```bash
python watch_price.py
```

### 4. Override paths if needed

The script supports:

- `LINKS_CSV_PATH`
- `SELECTOR_SCHEMA_PATH`
- `PRICE_STATE_PATH`
- `FETCH_TIMEOUT_SECONDS`
- `FETCH_URL`

Example:

```bash
LINKS_CSV_PATH=runtime_data/links.csv SELECTOR_SCHEMA_PATH=runtime_data/site_selectors.json PRICE_STATE_PATH=runtime_data/price_memory.json python watch_price.py
```

## Understanding the Memory File

`price_memory.json` stores the last known price per URL.

A typical entry looks like:

```json
{
  "https://www.cervera.se/produkt/arabia-tuokio-skal-16-cm-koboltbla": {
    "last_checked": "2026-03-14",
    "last_message": "Current price: 235 kr",
    "price": "235 kr"
  }
}
```

The script uses this file to decide whether the item is:

- new
- unchanged
- increased
- decreased

## Troubleshooting

### Koofr: `401`

This means authentication failed.

Check:

- `KOOFR_EMAIL` is correct
- `KOOFR_APP_PASSWORD` is a Koofr app-specific password
- you did not use your normal Koofr account password

### Koofr: `directory not found`

This usually means `KOOFR_PATH` is wrong.

Use the Koofr-visible path, not your local disk path.

Example:

- wrong: `/Users/erikbergman/Koofr/prices_for_ida`
- right: `My desktop sync/prices_for_ida`

### No selector schema matched this URL

This means the URL domain does not match any site definition in `site_selectors.json`.

Check:

- the domain in the URL
- the `domains` list in the site schema
- any `url_contains` rules you added

### `site_selectors.json` download fails

Check:

- the file exists in Koofr
- it is named exactly `site_selectors.json`
- it is inside the folder pointed to by `KOOFR_PATH`

### Telegram message does not arrive

Check:

- the bot token is correct
- the chat ID is correct
- you already sent at least one message to the bot

### Scheduled run does not happen exactly on time

GitHub scheduled workflows are not real-time. They can be delayed by several minutes.

Also check:

- the workflow file is on the default branch
- the repository is not inactive in a way that disabled scheduled workflows

## Notes

- The current workflow still includes a temporary `Debug Koofr paths` step that was used during setup.
- Once you are satisfied that Koofr access is stable, that debug step can be removed.
