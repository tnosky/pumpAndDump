"""
Shared pytest fixtures for the freshmanPumpAndDump test suite.

Key design points:
- Tests never touch your real market.db. We point the app at a throwaway
  temp-file SQLite database via the DATABASE_URL env var (see app.py).
- Every test gets a fully reset database (fresh stocks, fresh market
  settings, no users/trades except the moderator) via the autouse
  `clean_db` fixture, so tests never depend on execution order.
- The moderator account credentials are fixed for the test run so tests
  can log in as the moderator deterministically.
"""
import os
import sys
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from freezegun import freeze_time

# --- Point the app at an isolated, throwaway database BEFORE it is imported ---
_TEST_DB_FD, TEST_DB_PATH = tempfile.mkstemp(suffix=".db")
os.close(_TEST_DB_FD)
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"
os.environ.setdefault("MODERATOR_USERNAME", "moderator")
os.environ.setdefault("MODERATOR_PASSWORD", "modpass123")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
for path in (PROJECT_ROOT, TESTS_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

import app as app_module  # noqa: E402  (import must happen after env vars are set)
from models import (  # noqa: E402
    db,
    User,
    Stock,
    Trade,
    Holding,
    PricePoint,
    MarketSetting,
    ClosedDate,
    AuditLog,
)

MODERATOR_USERNAME = os.environ["MODERATOR_USERNAME"]
MODERATOR_PASSWORD = os.environ["MODERATOR_PASSWORD"]

# A fixed Wednesday afternoon (within the default 12-20 market hours, and
# never a Sunday). Every test is frozen here by default so trading tests
# don't randomly fail depending on what day/hour you happen to run pytest.
# Individual tests can still nest their own freeze_time(...) to test other
# specific dates/hours (see test_market_hours.py and test_daily_limit.py).
DEFAULT_TEST_TIME = datetime(2026, 8, 19, 15, 0, 0, tzinfo=ZoneInfo("America/Denver"))


@pytest.fixture(autouse=True)
def default_frozen_time():
    with freeze_time(DEFAULT_TEST_TIME):
        yield


@pytest.fixture()
def app():
    app_module.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    yield app_module.app


@pytest.fixture(autouse=True)
def app_ctx(app):
    """Push an app context for the duration of every test."""
    with app.app_context():
        yield


@pytest.fixture(autouse=True)
def clean_db(app_ctx):
    """Wipe and reseed the database before every single test."""
    # Delete children before parents to respect foreign keys.
    Trade.query.delete()
    PricePoint.query.delete()
    Holding.query.delete()
    AuditLog.query.delete()
    ClosedDate.query.delete()
    User.query.filter_by(is_moderator=False).delete()
    Stock.query.delete()
    MarketSetting.query.delete()
    db.session.commit()
    app_module.seed()
    yield


@pytest.fixture()
def client(app):
    return app.test_client()


# --------------------------------------------------------------------------
# Helpers used across test modules
# --------------------------------------------------------------------------

def register(client, username, password="password123"):
    return client.post(
        "/register",
        data={"username": username, "password": password},
        follow_redirects=True,
    )


def login(client, username, password="password123"):
    return client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=True,
    )


def logout(client):
    return client.get("/logout", follow_redirects=True)


def moderator_login(client):
    return login(client, MODERATOR_USERNAME, MODERATOR_PASSWORD)


def approve(client, user_id, starting_cash=10):
    return client.post(
        "/moderator",
        data={"action": "approve", "user_id": str(user_id), "starting_cash": str(starting_cash)},
        follow_redirects=True,
    )


def register_and_approve(client, username, password="password123", starting_cash=10, cash_override=None):
    """Register a new user, approve them as the moderator, then log them back in.

    `starting_cash` must be within the moderator's $5-$20 approval bounds,
    and determines whether the $12 starter-share grant fires (>= $12 triggers
    it; below that skips it). If a test just wants a specific amount of
    spending cash and doesn't care about the grant, pass `cash_override` to
    set the user's cash directly after approval (bypassing the $5-$20 cap
    and any grant deduction).
    """
    register(client, username, password)
    user = User.query.filter_by(username=username).first()
    moderator_login(client)
    approve(client, user.id, starting_cash)
    if cash_override is not None:
        user.cash = cash_override
        db.session.commit()
    logout(client)
    login(client, username, password)
    db.session.refresh(user)
    return user


def open_market_all_day(settings=None):
    """Widen market hours to 0-24 so trading tests aren't hour-dependent."""
    settings = settings or MarketSetting.query.first()
    settings.market_enabled = True
    settings.market_open_hour = 0
    settings.market_close_hour = 24
    db.session.commit()
    return settings


def get_stock(ticker="ROB"):
    return Stock.query.filter_by(ticker=ticker).first()


def buy(client, ticker, shares):
    return client.post(
        "/trade",
        data={"ticker": ticker, "side": "BUY", "shares": str(shares)},
        headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
    )


def sell(client, ticker, shares):
    return client.post(
        "/trade",
        data={"ticker": ticker, "side": "SELL", "shares": str(shares)},
        headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
    )
