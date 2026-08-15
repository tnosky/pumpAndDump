from datetime import datetime

import pytest


def test_seeded_stocks_and_tickers(project, helpers):
    stocks = helpers["Stock"].query.order_by(helpers["Stock"].id).all()
    assert [(s.ticker, s.name) for s in stocks] == [
        ("ROB", "Reid O'Brien"),
        ("WIK", "Lukas Wik"),
        ("ZROD", "Zarien Rodriguez"),
        ("IVAS", "Isaac Vasquez"),
        ("DWIL", "David Williams"),
        ("HAL", "Miles Halvorsen"),
    ]
    assert all(s.price == pytest.approx(0.100) for s in stocks)
    assert all(s.shares_outstanding == 300 for s in stocks)


def test_registration_requires_moderator_approval(project):
    client = project.app.test_client()
    response = client.post("/register", data={"username": "alice", "password": "pw"}, follow_redirects=True)
    assert response.status_code == 200

    from models import User

    user = User.query.filter_by(username="alice").one()
    assert not user.is_approved

    login = client.post("/login", data={"username": "alice", "password": "pw"}, follow_redirects=True)
    assert b"waiting for trent approval" in login.data


def test_duplicate_username_rejected(project, helpers):
    helpers["make_user"]("alice")
    client = project.app.test_client()
    response = client.post("/register", data={"username": "alice", "password": "other"})
    assert response.status_code == 200
    assert b"already taken" in response.data


def test_moderator_can_approve_user(project, helpers):
    from models import User

    pending = helpers["make_user"]("alice", cash=0, approved=False)
    mod = helpers["User"].query.filter_by(is_moderator=True).one()
    client = project.app.test_client()
    helpers["login"](client, mod)

    response = client.post(
        "/moderator",
        data={"action": "approve", "user_id": pending.id, "starting_cash": "15"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    user = User.query.get(pending.id)
    assert user.is_approved
    assert user.starting_cash == pytest.approx(15)
    assert user.cash == pytest.approx(15)


def test_non_moderator_cannot_access_moderator_page(project, helpers):
    user = helpers["make_user"]("alice")
    client = project.app.test_client()
    helpers["login"](client, user)
    response = client.get("/moderator", follow_redirects=True)
    assert b"Trent access required" in response.data


def test_market_closed_friday_and_open_saturday(project, helpers, monkeypatch):
    from market import market_is_open
    from zoneinfo import ZoneInfo

    settings = helpers["MarketSetting"].query.first()
    state = helpers["MarketState"].query.first()
    state.phase = "OPEN"
    helpers["db"].session.commit()
    tz = ZoneInfo("America/Denver")

    from tests.conftest import set_market_open

    friday = datetime(2026, 8, 14, 13, 0, tzinfo=tz)
    set_market_open(monkeypatch, project, friday)
    assert not market_is_open(settings, state)

    saturday = datetime(2026, 8, 15, 13, 0, tzinfo=tz)
    set_market_open(monkeypatch, project, saturday)
    assert market_is_open(settings, state)


def test_special_closed_date_blocks_market(project, helpers, monkeypatch):
    from datetime import date
    from market import market_is_open
    from zoneinfo import ZoneInfo
    from models import ClosedDate
    from tests.conftest import set_market_open

    settings = helpers["MarketSetting"].query.first()
    state = helpers["MarketState"].query.first()
    day = date(2026, 8, 17)
    helpers["db"].session.add(ClosedDate(day=day, note="test holiday"))
    helpers["db"].session.commit()

    set_market_open(monkeypatch, project, datetime(2026, 8, 17, 13, 0, tzinfo=ZoneInfo("America/Denver")))
    assert not market_is_open(settings, state)


def test_market_closed_outside_hours(project, helpers, monkeypatch):
    from market import market_is_open
    from zoneinfo import ZoneInfo
    from tests.conftest import set_market_open

    settings = helpers["MarketSetting"].query.first()
    state = helpers["MarketState"].query.first()
    state.phase = "OPEN"
    helpers["db"].session.commit()
    set_market_open(monkeypatch, project, datetime(2026, 8, 15, 11, 59, tzinfo=ZoneInfo("America/Denver")))
    assert not market_is_open(settings, state)
    set_market_open(monkeypatch, project, datetime(2026, 8, 15, 12, 0, tzinfo=ZoneInfo("America/Denver")))
    assert market_is_open(settings, state)
    set_market_open(monkeypatch, project, datetime(2026, 8, 15, 19, 59, tzinfo=ZoneInfo("America/Denver")))
    assert market_is_open(settings, state)
    set_market_open(monkeypatch, project, datetime(2026, 8, 15, 20, 0, tzinfo=ZoneInfo("America/Denver")))
    assert not market_is_open(settings, state)
