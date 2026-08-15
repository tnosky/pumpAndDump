from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import session

from extensions import socketio
from config import MARKET_OPEN_HOUR, MARKET_CLOSE_HOUR, MARKET_TIMEZONE, IPO_START, IPO_END
from market import change_from_start, market_is_open
from models import ClosedDate, IPOOrder, MarketSetting, MarketState, Stock, Trade, User
from analytics import stock_stats, user_holdings, user_stats



def market_timing(settings, state):
    now = datetime.now(ZoneInfo(MARKET_TIMEZONE))
    closed = {item.day for item in ClosedDate.query.all()}
    ipo_start = datetime.fromisoformat(IPO_START)
    ipo_end = datetime.fromisoformat(IPO_END)
    if state and state.phase == "IPO":
        if now < ipo_start:
            return {"label": "IPO", "next_change": ipo_start.isoformat(), "ipo_seconds": int((ipo_end - now).total_seconds())}
        if now < ipo_end:
            return {"label": "IPO", "next_change": ipo_end.isoformat(), "ipo_seconds": int((ipo_end - now).total_seconds())}
        closed = {item.day for item in ClosedDate.query.all()}
    if not settings or not settings.market_enabled:
        return {"label": "MANUALLY CLOSED", "next_change": None}

    if now.weekday() != 4 and now.date() not in closed and MARKET_OPEN_HOUR <= now.hour < MARKET_CLOSE_HOUR:
        next_change = now.replace(hour=MARKET_CLOSE_HOUR, minute=0, second=0, microsecond=0)
        return {"label": "OPEN", "next_change": next_change.isoformat()}

    candidate = now.replace(hour=MARKET_OPEN_HOUR, minute=0, second=0, microsecond=0)
    if now >= candidate:
        candidate = candidate + timedelta(days=1)
    while candidate.weekday() == 4 or candidate.date() in closed:
        candidate += timedelta(days=1)
    return {"label": "CLOSED", "next_change": candidate.isoformat()}

def market_payload():
    settings = MarketSetting.query.first()
    stocks = []
    for stock in Stock.query.order_by(Stock.id).all():
        s = stock_stats(stock)
        stocks.append({
            "ticker": stock.ticker,
            "name": stock.name,
            "price": round(stock.price, 3),
            "change": round(s["change_pct"], 2),
            "market_cap": round(s["market_cap"], 2),
            "volume": s["volume"],
            "available": s["available"],
            "high": round(s["high"], 3),
            "low": round(s["low"], 3),
            "trades": s["trades"],
            "held": s["held"],
            "holder_count": s["holder_count"],
            "buy_shares": s["buy_shares"],
            "sell_shares": s["sell_shares"],
            "avg_trade_price": round(s["avg_trade_price"], 6),
            "volatility": round(s["volatility"], 4),
            "largest_holder": s["largest_holder"].user.username if s["largest_holder"] else None,
            "largest_holder_shares": (s["largest_holder"].shares or 0) if s["largest_holder"] else 0,
        })

    recent_trades = []
    for trade in Trade.query.order_by(Trade.created_at.desc()).limit(30).all():
        recent_trades.append({
            "user": trade.user.username,
            "side": trade.side,
            "shares": trade.shares,
            "ticker": trade.stock.ticker,
            "price": trade.price,
            "total": trade.total,
            "created_at": trade.created_at.isoformat(),
        })

    users = User.query.filter_by(is_approved=True, is_moderator=False).all()
    users.sort(key=lambda user: user.net_worth(), reverse=True)
    leaderboard = []
    for user in users:
        s = user_stats(user)
        leaderboard.append({
            "username": user.username,
            "net_worth": round(s["net_worth"], 2),
            "cash": round(s["cash"], 2),
            "invested": round(s["invested"], 2),
            "return_pct": round(s["return_pct"], 2),
            "realized": round(s["realized"], 2),
            "unrealized": round(s["unrealized"], 2),
            "trades": s["trades"],
        })

    account = None
    user_id = session.get("user_id")
    if user_id:
        user = User.query.get(user_id)
        if user:
            account = {
                "cash": round(user.cash, 2),
                "invested": round(user.invested_value(), 2),
                "net_worth": round(user.net_worth(), 2),
                "return_pct": round(user.total_return(), 2),
                "holdings": [
                    {
                        "ticker": h["ticker"],
                        "shares": h["shares"],
                        "avg_cost": round(h["avg_cost"], 3),
                        "price": round(h["price"], 3),
                        "value": round(h["value"], 2),
                        "allocation": round(h["allocation"], 1),
                        "unrealized": round(h["unrealized"], 2),
                    }
                    for h in user_holdings(user)
                ],
            }

    state = MarketState.query.first()
    timing = market_timing(settings, state)
    ipo_users = User.query.filter_by(is_approved=True, is_moderator=False).all()
    ipo_submitted = sum(1 for user in ipo_users if sum((order.shares or 0) for order in user.ipo_orders) > 0)
    ipo_demand = {}
    for stock in Stock.query.order_by(Stock.id).all():
        ipo_demand[stock.ticker] = sum((order.shares or 0) for order in IPOOrder.query.filter_by(stock_id=stock.id).all())
    return {
        "market_open": market_is_open(settings, state),
        "market_label": timing["label"],
        "market_phase": state.phase if state else "OPEN",
        "market_cash": round(state.market_cash, 2) if state else 0.0,
        "next_change": timing["next_change"],
        "ipo_seconds": timing.get("ipo_seconds"),
        "ipo": {
            "participants": len(ipo_users),
            "submitted": ipo_submitted,
            "all_submitted": bool(ipo_users) and ipo_submitted == len(ipo_users),
            "demand": ipo_demand,
        },
        "stocks": stocks,
        "recent_trades": recent_trades,
        "leaderboard": leaderboard,
        "account": account,
    }


def broadcast_market_update(trade=None):
    payload = market_payload()
    if trade:
        payload["trade"] = {
            "user": trade.user.username,
            "side": trade.side,
            "shares": trade.shares,
            "ticker": trade.stock.ticker,
            "price": trade.price,
            "total": trade.total,
            "created_at": trade.created_at.isoformat() if trade.created_at else datetime.utcnow().isoformat(),
        }
        payload["price_point"] = {
            "ticker": trade.stock.ticker,
            "price": trade.stock.price,
            "created_at": trade.created_at.isoformat() if trade.created_at else datetime.utcnow().isoformat(),
        }
    socketio.emit("market_update", payload)
