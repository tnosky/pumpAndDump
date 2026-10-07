# Pump and Dump

A private stock market for a group of friends, where the stocks are the friends.

Everyone gets a few dollars of fake cash and trades six stocks. There's no outside market. Prices only move when people buy and sell, so the game is about who can pump a stock and get out before everyone else dumps it.

## How it works

1. **Join.** Register an account. The moderator approves it and sets your starting cash ($5 to $20). If that covers it, you also get 20 shares of each stock at the $0.10 IPO price.
2. **Trade.** Buy or sell 1 to 50 shares at a time. Every share bought pushes the price up $0.0003 and every share sold pushes it down the same, so big orders move the price against you as they fill. Prices never go below $0.001.
3. **Watch.** Prices, the ticker, and the leaderboard update live for everyone through Socket.IO. Each stock has a price chart and stats, and each player has a profile with their holdings and portfolio history.

**Rules.** No shorting or margin. Each player can buy and sell up to 50 shares per stock per day, tracked separately. The market is open 12 PM to 8 PM Mountain time and closed Sundays.

**Moderator.** From `/moderator` the moderator approves players, sets cash and passwords, changes market hours and daily limits, adds closed days, opens or closes the market by hand, and can delete accounts.

## Repo layout

```
app.py          Flask app: routes, moderator panel, seeding, DB migrations
market.py       Trade execution, price movement, market hours, daily limits
models.py       SQLAlchemy models (users, stocks, holdings, trades, price history)
analytics.py    Stock stats, player stats, portfolio history
realtime.py     Socket.IO live updates
auth.py         Login and moderator checks
config.py       Game constants (prices, limits, hours)
templates/      Pages
static/         JS, CSS
tests/          pytest suite
```

## Usage

**Run locally**

```bash
pip install -r requirements.txt
cp .env.example .env     # then set SECRET_KEY, MODERATOR_USERNAME, MODERATOR_PASSWORD
python app.py
```

Open `http://localhost:5000` and log in as the moderator to approve players. The database is a SQLite file, `market.db`. Delete it to start a fresh game.

**Tests**

```bash
pip install -r requirements-dev.txt freezegun
python -m pytest -q
```

**Deploy.** Set up for Railway with `railway.toml`, a `Procfile`, and a `/health` check. Set the three `.env` variables in Railway. Attach a persistent volume, or the database resets whenever the service is replaced.

## Limitations

- SQLite and a single process. Fine for a friend group, not for a crowd.
- Only `test_trading.py` passes right now. The other test files were written for an older IPO version of the game and need updating.
