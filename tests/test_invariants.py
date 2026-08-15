import pytest


def test_total_money_supply_stays_constant_through_ipo_and_trading(project, helpers):
    import market
    from models import IPOOrder, MarketState, User

    users = [helpers["make_user"](f"u{i}", cash=15) for i in range(4)]
    stocks = [helpers["get_stock"]("ROB"), helpers["get_stock"]("WIK")]
    for user in users:
        for stock in stocks:
            helpers["db"].session.add(IPOOrder(user_id=user.id, stock_id=stock.id, shares=20))
    helpers["db"].session.commit()

    start_supply = sum(u.cash for u in User.query.filter_by(is_moderator=False).all()) + MarketState.query.first().market_cash
    ok, _ = market.complete_ipo()
    assert ok
    after_ipo = sum(u.cash for u in User.query.filter_by(is_moderator=False).all()) + MarketState.query.first().market_cash
    assert after_ipo == pytest.approx(start_supply)

    settings = helpers["MarketSetting"].query.first()
    a = users[0]
    b = users[1]
    assert market.execute_trade(a, stocks[0], "BUY", 10, settings)[0]
    supply_after_buy = sum(u.cash for u in User.query.filter_by(is_moderator=False).all()) + MarketState.query.first().market_cash
    assert supply_after_buy == pytest.approx(start_supply)

    assert market.execute_trade(a, stocks[0], "SELL", 5, settings)[0]
    supply_after_sell = sum(u.cash for u in User.query.filter_by(is_moderator=False).all()) + MarketState.query.first().market_cash
    assert supply_after_sell == pytest.approx(start_supply)

    # another player can participate without changing the money supply
    assert market.execute_trade(b, stocks[1], "BUY", 5, settings)[0]
    assert sum(u.cash for u in User.query.filter_by(is_moderator=False).all()) + MarketState.query.first().market_cash == pytest.approx(start_supply)


def test_share_accounting_never_exceeds_outstanding(project, helpers):
    import market
    from models import IPOOrder

    users = [helpers["make_user"](f"u{i}", cash=15) for i in range(5)]
    stock = helpers["get_stock"]("ROB")
    for user in users:
        helpers["db"].session.add(IPOOrder(user_id=user.id, stock_id=stock.id, shares=40))
    helpers["db"].session.commit()
    ok, _ = market.complete_ipo()
    assert ok
    assert stock.shares_held() == 200
    assert stock.shares_available() == 100

    settings = helpers["MarketSetting"].query.first()
    for user in users:
        ok, _ = market.execute_trade(user, stock, "BUY", 1, settings)
        assert ok
    assert stock.shares_held() == 205
    assert stock.shares_held() <= stock.shares_outstanding
