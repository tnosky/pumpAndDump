# freshmanPumpAndDump test suite

The suite uses a temporary SQLite database per test session, so it does not touch the real `market.db` used by the site.

## Install

From the project folder:

```bash
python -m pip install -r requirements-dev.txt
```

If your `.venv` is active in PyCharm, the packages will be installed into that environment.

## Run everything

```bash
python -m pytest -q
```

## See every test name

```bash
python -m pytest -vv
```

## Run one area

```bash
python -m pytest tests/test_ipo.py -vv
python -m pytest tests/test_trading.py -vv
python -m pytest tests/test_routes.py -vv
python -m pytest tests/test_realtime.py -vv
```

## What the suite covers

- six seeded stocks and the required tickers
- account registration, login, approval, and session persistence
- moderator permissions
- Friday closure, normal hours, and special closed dates
- IPO open/closed timing
- private IPO requests and aggregate demand
- 0-50 IPO requests
- proportional oversubscription allocation
- IPO price calculation
- IPO market funding
- fixed total money supply
- 1-50 share normal trades
- repeated one-share price movement
- ten-share price movement and execution average
- sell-side price movement
- share availability
- insufficient cash
- insufficient market cash
- short-selling prevention
- invalid trade types
- market/IPO trade blocking
- trade and price-point persistence
- live `/api/market` payloads
- Socket.IO market-update broadcasts
- stock, portfolio, leaderboard, and user pages
- 404 and health routes


## Test clock

The suite resets the database for every test and simulates **Saturday, August 15, 2026 at 1:00 PM MDT**. That keeps normal market tests open while still testing the real Friday closure rule separately. Fresh tests start in the IPO phase; tests that need normal trading call the `open_market` helper.
