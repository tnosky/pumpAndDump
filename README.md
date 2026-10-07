# freshmanPumpAndDump

A small private stock market game for a group of friends.

## Stack

- Flask
- Flask-SocketIO
- Flask-SQLAlchemy
- SQLite
- Vanilla JavaScript
- Chart.js

## Local setup

```powershell
python -m venv .venv
.venv\\Scripts\\activate
python -m pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000

## Environment

Copy `.env.example` to `.env` and set:

- `SECRET_KEY`
- `MODERATOR_USERNAME`
- `MODERATOR_PASSWORD`

The app uses `America/Denver` for the market clock. `tzdata` is included for Windows.

## Market rules

- 6 stocks, uncapped shares (buy as many as your cash and the daily limit allow)
- IPO price: $0.100 (market cap is price × real shares held, no artificial floor)
- Prices display to three decimals
- Minimum price: $0.001
- 1-50 shares per transaction
- Daily limit: each user can buy up to a moderator-set number of shares per stock per day (default 50/day), and separately sell up to a moderator-set number of shares per stock per day (default 50/day). Buying and selling limits are tracked independently, so hitting one doesn't affect the other. Both are shown live on each stock's page.
- Starter grant: when approved, a user is automatically given 20 shares of each stock, priced at the original IPO price ($0.10/share, so $12.00 total). This never moves the live stock price and isn't recorded as a trade. If the moderator's chosen starting cash is less than $12, the user just gets cash with no starter shares.
- No shorting or margin
- Market hours: moderator-editable (default 12:00 PM-8:00 PM, `America/Denver`)
- Sundays closed
- Moderator can add special closed dates
- Price movement: $0.0003 per share of trade pressure

## Moderator settings

From `/moderator`, the moderator can live-edit:

- Market open/close hour
- Daily per user, per-stock share purchase limit
- Daily per user, per-stock share sell limit
- User approval starting cash ($5-$20), passwords, and cash balances
- Special closed dates
- Manually toggle the market open/closed

## Running the test suite

The `tests/` folder has a full pytest suite covering auth, trading, the
daily share limit, market hours, moderator actions, and the JSON API. It
runs against a throwaway temp-file database, so it never touches your real
`market.db`.

```bash
pip install -r requirements-test.txt
pytest
```

Run a single file or test:

```bash
pytest tests/test_daily_limit.py
pytest tests/test_trading.py -k test_buy_increases_price
```

See `tests/README.md` for more detail on what's covered.

## Railway

Set these variables in Railway:

```text
SECRET_KEY=<long random value>
MODERATOR_USERNAME=<your moderator username>
MODERATOR_PASSWORD=<your moderator password>
```

The project includes `Procfile`, `railway.toml`, and `/health` for deployment.

For a private friend-group game, SQLite is intentionally kept simple. Railway's local filesystem should be treated as disposable storage, so use a persistent volume if you need the database to survive service replacement.

## Resetting the local database

Stop the app and delete `market.db` from the project folder, then restart the app.

## Milestones

### 1
Core users, moderator approval, trading, portfolios, market hours, SQLite.

### 2
Socket.IO live market updates and live ticker/leaderboard/account updates.

### 3
Stock analytics, trader profiles, sortable leaderboard, portfolio history and zoomable charts.

### 4
UI polish, deployment files, health check, error pages, loading/trade states, improved moderator UX, and responsive layout.

### 5
Removed the fixed 300-share-per-stock trading cap, added a moderator-configurable daily per-user/per-stock buy limit, and made market hours moderator-editable at runtime. Added a full pytest test suite (`tests/`).

### 6
New users are automatically granted 20 shares of each stock at IPO price ($12.00 total) when approved, if their starting cash covers it. Fixed a bug where the portfolio equity-curve chart didn't account for this starter grant.

### 7
Added a moderator-editable daily sell limit per user/per stock (separate from the buy limit). Both the buy and sell limits/remaining are now shown live on each stock's page.

### 8
Market cap now always equals price × real shares held, with no artificial floor. Previously it used a fixed 300-share baseline (from the original IPO design) and wouldn't move until real ownership exceeded that, which looked wrong once the starter grant made real float much smaller than 300.

### 9
Moderator can now permanently delete an approved user's account (with a confirmation prompt), which cascades to remove their holdings and trade history. The moderator's own account can't be deleted this way.
