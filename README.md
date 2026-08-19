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
- IPO price: $0.100
- Prices display to three decimals
- Minimum price: $0.001
- 1-50 shares per transaction
- No shorting or margin
- Market hours: 12:00 PM-8:00 PM MDT
- Sundays closed
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
