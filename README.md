# freshmanPumpAndDump

A small private stock-market game for a group of friends.

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

- 6 stocks, 300 shares each
- IPO starts at $0.100
- Every approved player must submit at least one IPO request before the IPO can close
- IPO requests are private; players see aggregate demand only
- Oversubscribed IPOs are allocated proportionally
- IPO price moves with demand and stays between $0.075 and $0.150
- IPO money moves into the market cash pool
- Prices display to three decimals, but the underlying price keeps higher precision
- Minimum price: $0.001
- 1-50 shares per normal transaction
- No shorting or margin
- The market pool is the counterparty for normal buys and sells
- A sale is rejected if the market pool cannot afford it
- Money is conserved between player wallets and the market pool except for moderator edits
- Market hours: 12:00 PM-8:00 PM MDT
- Fridays closed
- IPO: August 15, 2026, 12:00 PM-4:00 PM MDT
- 12 players x $15 = $180 total starting cash
- 6 stocks x $30 = $180 base market cap
- Moderator can add special closed dates
- Price movement: $0.0003 per share of trade pressure

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

Stop the app and delete `market.db` from the project folder, then restart the app. A fresh database starts in the IPO phase.

## Milestones

### 1
Core users, moderator approval, trading, portfolios, market hours, SQLite.

### 2
Socket.IO live market updates and live ticker/leaderboard/account updates.

### 3
Stock analytics, trader profiles, sortable leaderboard, portfolio history and zoomable charts.

### 4
UI polish, deployment files, health check, error pages, loading/trade states, improved moderator UX, and responsive layout.

## Running tests

Install the test dependency once:

```bash
python -m pip install pytest
```

Run the full suite:

```bash
python -m pytest -q
```

Run with more detail:

```bash
python -m pytest -vv
```

The tests use a temporary SQLite database, so they do not touch your real `market.db`.
