"""
Core trading mechanics: buying, selling, unlimited share supply, pricing,
holdings/avg-cost tracking, and input validation.

All tests use open_market_all_day() so trading isn't dependent on the
real-world clock or day of week. Market-hours-specific behavior is covered
separately in test_market_hours.py.
"""
from conftest import buy, get_stock, open_market_all_day, register_and_approve, sell
from config import MIN_PRICE, PRICE_STEP
from models import Holding, Trade, User


def test_buy_succeeds_and_updates_cash_and_holdings(client):
    user = register_and_approve(client, "trader1", starting_cash=10)
    open_market_all_day()
    resp = buy(client, "ROB", 10)
    data = resp.get_json()
    assert resp.status_code == 200
    assert data["ok"] is True
    assert data["trade"]["shares"] == 10
    assert data["trade"]["side"] == "BUY"

    db_user = User.query.get(user.id)
    holding = Holding.query.filter_by(user_id=user.id, stock_id=get_stock("ROB").id).first()
    assert db_user.cash < 20  # cash was spent
    assert holding.shares == 10


def test_buy_increases_price(client):
    register_and_approve(client, "trader2", starting_cash=10)
    open_market_all_day()
    stock = get_stock("ROB")
    price_before = stock.price
    buy(client, "ROB", 5)
    price_after = get_stock("ROB").price
    assert price_after > price_before
    # Each share nudges price up by PRICE_STEP.
    assert round(price_after - price_before, 6) == round(PRICE_STEP * 5, 6)


def test_sell_decreases_price(client):
    register_and_approve(client, "trader3", starting_cash=10)
    open_market_all_day()
    buy(client, "ROB", 10)
    price_before_sell = get_stock("ROB").price
    sell(client, "ROB", 5)
    price_after_sell = get_stock("ROB").price
    assert price_after_sell < price_before_sell


def test_sell_returns_cash_and_reduces_holding(client):
    user = register_and_approve(client, "trader4", starting_cash=10)
    open_market_all_day()
    buy(client, "ROB", 10)
    cash_after_buy = User.query.get(user.id).cash
    sell(client, "ROB", 4)
    cash_after_sell = User.query.get(user.id).cash
    holding = Holding.query.filter_by(user_id=user.id).first()
    assert cash_after_sell > cash_after_buy
    assert holding.shares == 6


def test_selling_all_shares_removes_holding_row(client):
    user = register_and_approve(client, "trader5", starting_cash=10)
    open_market_all_day()
    buy(client, "ROB", 5)
    sell(client, "ROB", 5)
    assert Holding.query.filter_by(user_id=user.id, stock_id=get_stock("ROB").id).first() is None


def test_cannot_sell_more_shares_than_owned(client):
    user = register_and_approve(client, "trader6", starting_cash=10)
    open_market_all_day()
    buy(client, "ROB", 3)
    resp = sell(client, "ROB", 10)
    data = resp.get_json()
    assert resp.status_code == 400
    assert data["ok"] is False
    assert "do not own enough shares" in data["error"].lower()
    # Holding should be unaffected.
    holding = Holding.query.filter_by(user_id=user.id).first()
    assert holding.shares == 3


def test_cannot_sell_with_no_holding(client):
    register_and_approve(client, "trader7", starting_cash=10)
    open_market_all_day()
    resp = sell(client, "ROB", 1)
    data = resp.get_json()
    assert data["ok"] is False
    assert "do not own enough shares" in data["error"].lower()


def test_cannot_buy_more_than_cash_allows(client):
    register_and_approve(client, "trader8", starting_cash=5)
    open_market_all_day()
    # 300+ shares at ~$0.10/share vastly exceeds $5 of cash.
    resp = buy(client, "ROB", 50)
    data = resp.get_json()
    assert data["ok"] is False
    assert "you need" in data["error"].lower()


def test_buy_of_zero_shares_rejected(client):
    register_and_approve(client, "trader9", starting_cash=10)
    open_market_all_day()
    resp = buy(client, "ROB", 0)
    data = resp.get_json()
    assert data["ok"] is False
    assert "1-50 shares" in data["error"]


def test_buy_of_negative_shares_rejected(client):
    register_and_approve(client, "trader10", starting_cash=10)
    open_market_all_day()
    resp = buy(client, "ROB", -5)
    data = resp.get_json()
    assert data["ok"] is False


def test_buy_over_per_transaction_max_rejected(client):
    register_and_approve(client, "trader11", starting_cash=10)
    open_market_all_day()
    resp = buy(client, "ROB", 51)
    data = resp.get_json()
    assert data["ok"] is False
    assert "1-50 shares" in data["error"]


def test_unlimited_shares_can_exceed_old_300_cap(client):
    """The old 300-shares-per-stock ceiling has been removed."""
    user = register_and_approve(client, "trader12", starting_cash=10, cash_override=1_000_000)
    open_market_all_day()
    # Buy in chunks of 50 (per-transaction max) across several days to
    # accumulate well beyond the old 300-share ceiling. Sundays are always
    # closed, so skip over them rather than treating every calendar day as
    # a tradable day.
    from freezegun import freeze_time
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    day = datetime(2026, 8, 19, 15, 0, 0, tzinfo=ZoneInfo("America/Denver"))  # Wednesday
    total_bought = 0
    while total_bought < 400:  # 400 shares, above the old 300 cap
        if day.weekday() != 6:
            with freeze_time(day):
                resp = buy(client, "ROB", 50)
            assert resp.get_json()["ok"] is True, resp.get_json()
            total_bought += 50
        day = day + timedelta(days=1)
    holding = Holding.query.filter_by(user_id=user.id).first()
    assert holding.shares == total_bought
    assert total_bought > 300  # exceeds the old hard cap


def test_avg_cost_updates_across_multiple_buys(client):
    user = register_and_approve(client, "trader13", starting_cash=10)
    open_market_all_day()
    buy(client, "ROB", 5)
    holding = Holding.query.filter_by(user_id=user.id).first()
    avg_after_first = holding.avg_cost
    buy(client, "ROB", 5)
    holding = Holding.query.filter_by(user_id=user.id).first()
    avg_after_second = holding.avg_cost
    # Price only goes up as we buy, so the average cost should rise too.
    assert avg_after_second > avg_after_first
    assert holding.shares == 10


def test_price_never_drops_below_minimum(client):
    user = register_and_approve(client, "trader14", starting_cash=10, cash_override=1_000_000)
    open_market_all_day()
    buy(client, "ROB", 50)
    # Sell far more than the price step math would allow without a floor.
    holding = Holding.query.filter_by(user_id=user.id).first()
    sell(client, "ROB", holding.shares)
    assert get_stock("ROB").price >= MIN_PRICE


def test_trade_rejected_when_stock_does_not_exist(client):
    register_and_approve(client, "trader15", starting_cash=10)
    open_market_all_day()
    resp = client.post(
        "/trade",
        data={"ticker": "ZZZ", "side": "BUY", "shares": "1"},
        headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
    )
    assert resp.status_code == 404


def test_invalid_side_rejected(client):
    register_and_approve(client, "trader16", starting_cash=10)
    open_market_all_day()
    resp = client.post(
        "/trade",
        data={"ticker": "ROB", "side": "HOLD", "shares": "1"},
        headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
    )
    data = resp.get_json()
    assert data["ok"] is False
    assert "invalid trade type" in data["error"].lower()


def test_successful_trade_is_recorded(client):
    user = register_and_approve(client, "trader17", starting_cash=10)
    open_market_all_day()
    buy(client, "ROB", 3)
    trade = Trade.query.filter_by(user_id=user.id).first()
    assert trade is not None
    assert trade.side == "BUY"
    assert trade.shares == 3
    assert trade.stock_id == get_stock("ROB").id
