from datetime import datetime

import pytest


def test_ipo_clock_is_active_during_window(project, helpers, monkeypatch):
    import market
    from zoneinfo import ZoneInfo
    from tests.conftest import set_ipo_clock

    tz = ZoneInfo("America/Denver")
    set_ipo_clock(monkeypatch, project, datetime(2026, 8, 16, 15, 0, tzinfo=tz))
    assert market.ipo_is_active()

    set_ipo_clock(monkeypatch, project, datetime(2026, 8, 16, 18, 0, tzinfo=tz))
    assert not market.ipo_is_active()
    assert market.ipo_seconds_remaining() == 0


def test_ipo_rejects_requests_outside_window(project, helpers, monkeypatch):
    import market
    from zoneinfo import ZoneInfo
    from tests.conftest import set_ipo_clock

    user = helpers["make_user"]("alice")
    stock = helpers["get_stock"]()
    tz = ZoneInfo("America/Denver")
    set_ipo_clock(monkeypatch, project, datetime(2026, 8, 16, 11, 59, tzinfo=tz))
    ok, message = market.save_ipo_order(user, stock, 10)
    assert not ok
    assert "has not opened" in message

    set_ipo_clock(monkeypatch, project, datetime(2026, 8, 16, 18, 1, tzinfo=tz))
    ok, message = market.save_ipo_order(user, stock, 10)
    assert not ok
    assert "ended" in message


def test_ipo_request_limit_and_update(project, helpers, monkeypatch):
    import market
    from zoneinfo import ZoneInfo
    from tests.conftest import set_ipo_clock

    user = helpers["make_user"]("alice")
    stock = helpers["get_stock"]()
    set_ipo_clock(monkeypatch, project, datetime(2026, 8, 16, 15, 0, tzinfo=ZoneInfo("America/Denver")))

    ok, _ = market.save_ipo_order(user, stock, 50)
    assert ok
    ok, _ = market.save_ipo_order(user, stock, 20)
    assert ok
    ok, message = market.save_ipo_order(user, stock, 51)
    assert not ok
    assert "between 0 and 50" in message

    from models import IPOOrder
    assert IPOOrder.query.filter_by(user_id=user.id, stock_id=stock.id).one().shares == 20


def test_ipo_requires_every_approved_player_to_submit(project, helpers):
    import market

    a = helpers["make_user"]("alice")
    helpers["make_user"]("bob")
    stock = helpers["get_stock"]()
    from models import IPOOrder
    helpers["db"].session.add(IPOOrder(user_id=a.id, stock_id=stock.id, shares=10))
    helpers["db"].session.commit()

    ok, message = market.complete_ipo()
    assert not ok
    assert "bob" in message


def test_ipo_oversubscription_is_proportional(project, helpers):
    import market
    from models import IPOOrder, Trade, MarketState

    users = [helpers["make_user"](f"u{i}") for i in range(7)]
    stock = helpers["get_stock"]()
    for user in users:
        helpers["db"].session.add(IPOOrder(user_id=user.id, stock_id=stock.id, shares=50))
    helpers["db"].session.commit()

    ok, result = market.complete_ipo()
    assert ok
    allocations = [item["allocated"] for item in result if item["ticker"] == "ROB"]
    assert sum(allocations) == 300
    assert max(allocations) - min(allocations) <= 1
    assert all(a in {42, 43} for a in allocations)
    assert stock.price > 0.100
    assert Trade.query.filter_by(side="IPO").count() == 7
    assert MarketState.query.first().phase == "OPEN"


def test_ipo_is_repriced_from_demand(project, helpers):
    import market

    user = helpers["make_user"]("alice")
    stock = helpers["get_stock"]()
    from models import IPOOrder
    helpers["db"].session.add(IPOOrder(user_id=user.id, stock_id=stock.id, shares=50))
    helpers["db"].session.commit()
    base = market.ipo_price_for_demand(300)
    high = market.ipo_price_for_demand(600)
    assert base == pytest.approx(0.100)
    assert high > base
    assert high <= 0.150


def test_ipo_funds_market_pool_without_creating_money(project, helpers):
    import market
    from models import IPOOrder, User, MarketState

    a = helpers["make_user"]("alice", cash=15)
    b = helpers["make_user"]("bob", cash=15)
    stock = helpers["get_stock"]()
    for user in (a, b):
        helpers["db"].session.add(IPOOrder(user_id=user.id, stock_id=stock.id, shares=50))
    helpers["db"].session.commit()

    before = sum(u.cash for u in User.query.filter_by(is_moderator=False).all()) + MarketState.query.first().market_cash
    ok, _ = market.complete_ipo()
    assert ok
    after = sum(u.cash for u in User.query.filter_by(is_moderator=False).all()) + MarketState.query.first().market_cash
    assert after == pytest.approx(before)
