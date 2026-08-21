from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import session

from extensions import socketio
from config import MARKET_TIMEZONE
from market import change_from_start, close_hour, daily_remaining, market_is_open, open_hour
from models import ClosedDate, MarketSetting, Stock, Trade, User
from analytics import stock_stats, user_holdings, user_stats



def market_timing(settings):
    now = datetime.now(ZoneInfo(MARKET_TIMEZONE))
    closed = {item.day for item in ClosedDate.query.all()}
    if not settings or not settings.market_enabled:
        return {"label": "MANUALLY CLOSED", "next_change": None}

    o_hour, c_hour = open_hour(settings), close_hour(settings)
    if now.weekday() != 6 and now.date() not in closed and o_hour <= now.hour < c_hour:
        # c_hour can legitimately be 24 (moderator set "open all day"), and
        # datetime.replace() only accepts hours 0-23, so treat hour 24 as
        # midnight of the following day rather than crashing.
        if c_hour >= 24:
            next_change = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            next_change = now.replace(hour=c_hour, minute=0, second=0, microsecond=0)
        return {"label": "OPEN", "next_change": next_change.isoformat()}

    candidate = now.replace(hour=o_hour, minute=0, second=0, microsecond=0)
    if now >= candidate:
        candidate = candidate + timedelta(days=1)
    while candidate.weekday() == 6 or candidate.date() in closed:
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
            daily_remaining_by_ticker = {}
            for stock in Stock.query.all():
                buy_remaining, buy_limit = daily_remaining(user.id, stock.id, settings, side="BUY")
                sell_remaining, sell_limit = daily_remaining(user.id, stock.id, settings, side="SELL")
                daily_remaining_by_ticker[stock.ticker] = {
                    "buy_remaining": buy_remaining,
                    "buy_limit": buy_limit,
                    "sell_remaining": sell_remaining,
                    "sell_limit": sell_limit,
                }
            account = {
                "cash": round(user.cash, 2),
                "invested": round(user.invested_value(), 2),
                "net_worth": round(user.net_worth(), 2),
                "return_pct": round(user.total_return(), 2),
                "daily_remaining": daily_remaining_by_ticker,
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

    timing = market_timing(settings)
    return {
        "market_open": market_is_open(settings),
        "market_label": timing["label"],
        "next_change": timing["next_change"],
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
