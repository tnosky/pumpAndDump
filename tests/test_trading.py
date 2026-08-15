import pytest


def test_buy_50_limit(project, helpers):
    import market

    user = helpers["make_user"]("alice", cash=50)
    stock = helpers["get_stock"]()
    helpers["open_market"](market_cash=100)
    settings = helpers["MarketSetting"].query.first()

    ok, _ = market.execute_trade(user, stock, "BUY", 51, settings)
    assert not ok

    ok, trade = market.execute_trade(user, stock, "BUY", 50, settings)
    assert ok
    assert trade.shares == 50


def test_repeated_one_share_purchases_accumulate_price(project, helpers):
    import market

    user = helpers["make_user"]("alice", cash=50)
    stock = helpers["get_stock"]()
    helpers["open_market"](market_cash=100)
    settings = helpers["MarketSetting"].query.first()

    for _ in range(10):
        ok, _ = market.execute_trade(user, stock, "BUY", 1, settings)
        assert ok

    assert stock.price == pytest.approx(0.103, abs=1e-9)


def test_buy_ten_matches_ten_one_share_price_move(project, helpers):
    import market

    user = helpers["make_user"]("alice", cash=50)
    stock = helpers["get_stock"]()
    helpers["open_market"](market_cash=100)
    settings = helpers["MarketSetting"].query.first()

    ok, trade = market.execute_trade(user, stock, "BUY", 10, settings)
    assert ok
    assert stock.price == pytest.approx(0.103, abs=1e-9)
    assert trade.price == pytest.approx(0.10135, abs=1e-9)
    assert trade.total == pytest.approx(1.0135, abs=1e-9)


def test_sell_moves_price_down(project, helpers):
    import market

    user = helpers["make_user"]("alice", cash=50)
    stock = helpers["get_stock"]()
    helpers["open_market"](market_cash=100)
    settings = helpers["MarketSetting"].query.first()

    assert market.execute_trade(user, stock, "BUY", 10, settings)[0]
    assert stock.price == pytest.approx(0.103)
    ok, trade = market.execute_trade(user, stock, "SELL", 10, settings)
    assert ok
    assert stock.price == pytest.approx(0.100)
    assert trade.total > 0


def test_cannot_sell_unowned_shares(project, helpers):
    import market

    user = helpers["make_user"]("alice", cash=15)
    stock = helpers["get_stock"]()
    helpers["open_market"](market_cash=100)
    settings = helpers["MarketSetting"].query.first()
    ok, message = market.execute_trade(user, stock, "SELL", 1, settings)
    assert not ok
    assert "do not own enough" in message


def test_cannot_buy_without_cash(project, helpers):
    import market

    user = helpers["make_user"]("alice", cash=0.001)
    stock = helpers["get_stock"]()
    helpers["open_market"](market_cash=100)
    settings = helpers["MarketSetting"].query.first()
    ok, message = market.execute_trade(user, stock, "BUY", 10, settings)
    assert not ok
    assert "need" in message.lower()
    assert stock.price == pytest.approx(0.100)


def test_cannot_buy_when_no_shares_available(project, helpers):
    import market

    a = helpers["make_user"]("alice", cash=100)
    b = helpers["make_user"]("bob", cash=100)
    stock = helpers["get_stock"]()
    helpers["open_market"](market_cash=1000)
    settings = helpers["MarketSetting"].query.first()

    ok, _ = market.execute_trade(a, stock, "BUY", 50, settings)
    assert ok
    stock.shares_outstanding = 50
    helpers["db"].session.commit()

    ok, message = market.execute_trade(b, stock, "BUY", 1, settings)
    assert not ok
    assert "not enough shares" in message


def test_market_cash_is_required_for_sell(project, helpers):
    import market

    user = helpers["make_user"]("alice", cash=50)
    stock = helpers["get_stock"]()
    helpers["open_market"](market_cash=0)
    settings = helpers["MarketSetting"].query.first()

    ok, _ = market.execute_trade(user, stock, "BUY", 10, settings)
    assert ok

    state = helpers["MarketState"].query.first()
    state.market_cash = 0
    helpers["db"].session.commit()

    ok, message = market.execute_trade(user, stock, "SELL", 10, settings)
    assert not ok
    assert "not currently have enough cash" in message


def test_total_money_is_conserved_through_trades(project, helpers):
    import market

    user = helpers["make_user"]("alice", cash=15)
    stock = helpers["get_stock"]()
    helpers["open_market"](market_cash=10)
    settings = helpers["MarketSetting"].query.first()

    before = helpers["balance_sheet"]()
    assert market.execute_trade(user, stock, "BUY", 10, settings)[0]
    after_buy = helpers["balance_sheet"]()
    assert after_buy == pytest.approx(before)

    assert market.execute_trade(user, stock, "SELL", 5, settings)[0]
    after_sell = helpers["balance_sheet"]()
    assert after_sell == pytest.approx(before)


def test_invalid_trade_side_and_share_count(project, helpers):
    import market

    user = helpers["make_user"]("alice", cash=15)
    stock = helpers["get_stock"]()
    helpers["open_market"](market_cash=100)
    settings = helpers["MarketSetting"].query.first()

    for side in ("", "HOLD", "BUYME"):
        ok, message = market.execute_trade(user, stock, side, 1, settings)
        assert not ok
        assert "invalid trade type" in message.lower()

    for shares in (0, -1, 51, 100):
        ok, message = market.execute_trade(user, stock, "BUY", shares, settings)
        assert not ok
        assert "1-50" in message


def test_trade_blocked_when_market_closed(project, helpers):
    import market

    user = helpers["make_user"]("alice", cash=15)
    stock = helpers["get_stock"]()
    helpers["open_market"](market_cash=100)
    settings = helpers["MarketSetting"].query.first()
    settings.market_enabled = False
    helpers["db"].session.commit()

    ok, message = market.execute_trade(user, stock, "BUY", 1, settings)
    assert not ok
    assert "market is closed" in message.lower()


def test_trade_blocked_during_ipo(project, helpers):
    import market

    user = helpers["make_user"]("alice", cash=15)
    stock = helpers["get_stock"]()
    state = helpers["MarketState"].query.first()
    state.phase = "IPO"
    settings = helpers["MarketSetting"].query.first()
    helpers["db"].session.commit()

    ok, message = market.execute_trade(user, stock, "BUY", 1, settings)
    assert not ok
    assert "IPO phase is active" in message


def test_trade_is_logged_and_price_point_created(project, helpers):
    import market
    from models import PricePoint, Trade

    user = helpers["make_user"]("alice", cash=15)
    stock = helpers["get_stock"]()
    helpers["open_market"](market_cash=100)
    settings = helpers["MarketSetting"].query.first()
    before_points = PricePoint.query.filter_by(stock_id=stock.id).count()
    ok, trade = market.execute_trade(user, stock, "BUY", 3, settings)
    assert ok
    assert Trade.query.filter_by(id=trade.id).one().shares == 3
    assert PricePoint.query.filter_by(stock_id=stock.id).count() == before_points + 1
