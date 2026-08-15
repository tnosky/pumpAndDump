import importlib
import os
import sys
from datetime import datetime, timezone

import pytest


@pytest.fixture(scope="session")
def project(tmp_path_factory):
    original_cwd = os.getcwd()
    db_dir = tmp_path_factory.mktemp("fpd-test-db")
    os.chdir(db_dir)

    for name in ["app", "market", "models", "analytics", "auth", "realtime", "extensions"]:
        sys.modules.pop(name, None)

    app_module = importlib.import_module("app")
    app_module.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    yield app_module
    os.chdir(original_cwd)


@pytest.fixture(autouse=True)
def app_context(project):
    with project.app.app_context():
        yield


@pytest.fixture(autouse=True)
def fixed_market_clock(monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    import market

    target = datetime(2026, 8, 16, 15, 0, tzinfo=ZoneInfo("America/Denver"))
    real_datetime = market.datetime

    class FrozenDateTime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return target.replace(tzinfo=None)
            return target.astimezone(tz)

    monkeypatch.setattr(market, "datetime", FrozenDateTime)
    yield


@pytest.fixture(autouse=True)
def fresh_database(project, app_context):
    app_module = project
    with app_module.app.app_context():
        app_module.db.drop_all()
        app_module.db.create_all()
        app_module.seed()

        from models import MarketSetting, MarketState, Trade

        state = MarketState.query.first()
        settings = MarketSetting.query.first()
        settings.market_enabled = True
        state.phase = "IPO"
        state.market_cash = 0.0
        state.ipo_completed_at = None
        app_module.db.session.commit()


def set_market_open(monkeypatch, project, dt):
    import market

    real_datetime = market.datetime

    class FrozenDateTime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return dt.replace(tzinfo=None)
            return dt.astimezone(tz)

    monkeypatch.setattr(market, "datetime", FrozenDateTime)
    return dt


def set_ipo_clock(monkeypatch, project, dt):
    return set_market_open(monkeypatch, project, dt)


@pytest.fixture
def helpers(project):
    from models import User, Stock, Holding, Trade, MarketState, MarketSetting, db

    def make_user(username, cash=15.0, approved=True, moderator=False):
        user = User(
            username=username,
            password="pw",
            is_approved=approved,
            is_moderator=moderator,
            starting_cash=cash,
            cash=cash,
        )
        db.session.add(user)
        db.session.commit()
        return user

    def login(client, user):
        client.post("/login", data={"username": user.username, "password": user.password})

    def open_market(market_cash=100.0):
        state = MarketState.query.first()
        settings = MarketSetting.query.first()
        state.phase = "OPEN"
        state.market_cash = market_cash
        settings.market_enabled = True
        db.session.commit()

    def get_stock(ticker="ROB"):
        return Stock.query.filter_by(ticker=ticker).one()

    def balance_sheet():
        users_cash = sum(u.cash for u in User.query.filter_by(is_moderator=False).all())
        market_cash = MarketState.query.first().market_cash
        return users_cash + market_cash

    return {
        "make_user": make_user,
        "login": login,
        "open_market": open_market,
        "get_stock": get_stock,
        "balance_sheet": balance_sheet,
        "User": User,
        "Stock": Stock,
        "Holding": Holding,
        "Trade": Trade,
        "MarketState": MarketState,
        "MarketSetting": MarketSetting,
        "db": db,
    }
