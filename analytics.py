from collections import defaultdict
from statistics import pstdev

from config import INITIAL_GRANT_SHARES, MIN_PRICE, PRICE_STEP, STOCK_SHARES, STOCK_START_PRICE
from models import Stock, Trade


def user_realized_gain(user):
    cost_basis = defaultdict(float)
    shares_held = defaultdict(int)
    realized = 0.0

    trades = Trade.query.filter_by(user_id=user.id).order_by(Trade.created_at, Trade.id).all()
    for trade in trades:
        key = trade.stock_id
        if trade.side == "BUY":
            shares_held[key] += trade.shares
            cost_basis[key] += trade.total
        else:
            held = shares_held[key]
            avg_cost = cost_basis[key] / held if held else 0.0
            realized += trade.total - (avg_cost * trade.shares)
            shares_held[key] = max(0, held - trade.shares)
            cost_basis[key] = avg_cost * shares_held[key]
    return realized


def user_unrealized_gain(user):
    return sum(
        (h.stock.price - (h.avg_cost or 0.0)) * (h.shares or 0)
        for h in user.holdings
        if (h.shares or 0) > 0
    )


def user_stats(user):
    realized = user_realized_gain(user)
    unrealized = user_unrealized_gain(user)
    return {
        "net_worth": user.net_worth(),
        "cash": user.cash,
        "invested": user.invested_value(),
        "return_pct": user.total_return(),
        "realized": realized,
        "unrealized": unrealized,
        "trades": len(user.trades),
    }


def stock_volatility(stock):
    prices = [STOCK_START_PRICE]
    points = sorted(stock.price_points, key=lambda p: p.created_at)
    prices.extend(p.price for p in points)
    if len(prices) < 2:
        return 0.0
    returns = []
    for prev, curr in zip(prices, prices[1:]):
        if prev:
            returns.append((curr - prev) / prev * 100)
    return pstdev(returns) if len(returns) > 1 else (abs(returns[0]) if returns else 0.0)


def stock_stats(stock):
    trades = Trade.query.filter_by(stock_id=stock.id).order_by(Trade.created_at, Trade.id).all()
    buy_shares = sum(t.shares for t in trades if t.side == "BUY")
    sell_shares = sum(t.shares for t in trades if t.side == "SELL")
    total_shares = sum(t.shares for t in trades)
    avg_trade_price = sum(t.price * t.shares for t in trades) / total_shares if total_shares else stock.price
    largest = max(stock.holdings, key=lambda h: (h.shares or 0), default=None)
    return {
        "price": stock.price,
        "change_pct": ((stock.price - STOCK_START_PRICE) / STOCK_START_PRICE * 100) if stock.price else 0.0,
        "market_cap": stock.market_cap(),
        "volume": stock.volume(),
        "trades": len(trades),
        "high": stock.all_time_high(),
        "low": stock.all_time_low(),
        "held": stock.shares_held(),
        "holder_count": sum(1 for h in stock.holdings if (h.shares or 0) > 0),
        "buy_shares": buy_shares,
        "sell_shares": sell_shares,
        "avg_trade_price": avg_trade_price,
        "volatility": stock_volatility(stock),
        "largest_holder": largest,
    }


def portfolio_history(user):
    stocks = {stock.id: stock for stock in Stock.query.all()}
    prices = {stock_id: STOCK_START_PRICE for stock_id in stocks}
    positions = defaultdict(int)
    # Account for the starter grant (20 shares of each stock at IPO price)
    # so the equity curve starts from the user's real initial position,
    # not just their post-grant cash balance.
    cash = user.starting_cash - (user.starter_grant_cost or 0.0)
    if user.starter_grant_cost:
        for stock_id in stocks:
            positions[stock_id] = INITIAL_GRANT_SHARES
    points = []

    trades = Trade.query.order_by(Trade.created_at, Trade.id).all()
    for trade in trades:
        if trade.side == "BUY":
            cash_change = -trade.total if trade.user_id == user.id else 0.0
            if trade.user_id == user.id:
                positions[trade.stock_id] += trade.shares
            prices[trade.stock_id] = prices[trade.stock_id] + PRICE_STEP * trade.shares
        else:
            cash_change = trade.total if trade.user_id == user.id else 0.0
            if trade.user_id == user.id:
                positions[trade.stock_id] = max(0, positions[trade.stock_id] - trade.shares)
            prices[trade.stock_id] = max(MIN_PRICE, prices[trade.stock_id] - PRICE_STEP * trade.shares)

        if trade.user_id == user.id:
            cash += cash_change

        value = cash + sum(shares * prices[stock_id] for stock_id, shares in positions.items())
        points.append({"time": trade.created_at.isoformat(), "value": round(value, 4)})

    if not points:
        points = [{"time": user.created_at.isoformat(), "value": round(user.net_worth(), 4)}]
    else:
        points[-1]["value"] = round(user.net_worth(), 4)
    return points


def user_holdings(user):
    rows = []
    total = user.invested_value()
    for holding in sorted(user.holdings, key=lambda h: h.stock.ticker):
        shares = holding.shares or 0
        if shares <= 0:
            continue
        value = shares * holding.stock.price
        rows.append({
            "ticker": holding.stock.ticker,
            "name": holding.stock.name,
            "shares": shares,
            "avg_cost": holding.avg_cost or 0.0,
            "price": holding.stock.price,
            "value": value,
            "unrealized": (holding.stock.price - (holding.avg_cost or 0.0)) * shares,
            "allocation": (value / total * 100) if total else 0.0,
        })
    return rows
