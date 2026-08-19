from datetime import datetime
from zoneinfo import ZoneInfo

from config import MARKET_TIMEZONE, MARKET_OPEN_HOUR, MARKET_CLOSE_HOUR, MIN_PRICE, PRICE_STEP
from models import AuditLog, ClosedDate, Holding, PricePoint, Trade, db


def market_is_open(settings):
    if not settings.market_enabled:
        return False
    now = datetime.now(ZoneInfo(MARKET_TIMEZONE))
    if now.weekday() == 6 or ClosedDate.query.filter_by(day=now.date()).first():
        return False
    return MARKET_OPEN_HOUR <= now.hour < MARKET_CLOSE_HOUR


def format_money(value):
    return f"${value:,.2f}"


def format_price(value):
    return f"${value:.3f}"


def change_from_start(stock):
    points = sorted(stock.price_points, key=lambda p: p.created_at)
    base = points[0].price if points else stock.price
    if base == 0:
        return 0.0
    return ((stock.price - base) / base) * 100


def execute_trade(user, stock, side, shares, settings):
    if not market_is_open(settings):
        return False, "The market is closed."
    if side not in {"BUY", "SELL"}:
        return False, "Invalid trade type."
    if shares < 1 or shares > 50:
        return False, "You can trade 1-50 shares at a time."

    holding = Holding.query.filter_by(user_id=user.id, stock_id=stock.id).first()
    if holding and holding.shares is None:
        holding.shares = 0
    if holding and holding.avg_cost is None:
        holding.avg_cost = 0.0

    if side == "BUY":
        if stock.shares_available() < shares:
            return False, "There are not enough shares available."
        total = 0.0
        prices = []
        for _ in range(shares):
            price = stock.price
            total += price
            prices.append(price)
            stock.price = max(stock.price + PRICE_STEP, MIN_PRICE)
        if user.cash < total:
            db.session.rollback()
            return False, f"You need {format_money(total)}."
        user.cash -= total
        if holding is None:
            holding = Holding(user_id=user.id, stock_id=stock.id)
            db.session.add(holding)
        old_value = (holding.shares or 0) * (holding.avg_cost or 0.0)
        holding.shares = (holding.shares or 0) + shares
        holding.avg_cost = (old_value + total) / holding.shares
    else:
        if holding is None or (holding.shares or 0) < shares:
            return False, "You do not own enough shares."
        total = 0.0
        for _ in range(shares):
            stock.price = max(MIN_PRICE, stock.price - PRICE_STEP)
            total += stock.price
        user.cash += total
        holding.shares = (holding.shares or 0) - shares
        if holding.shares == 0:
            holding.avg_cost = 0.0

    if holding and holding.shares == 0:
        db.session.delete(holding)

    trade = Trade(
        user_id=user.id,
        stock_id=stock.id,
        side=side,
        shares=shares,
        price=total / shares,
        total=total,
    )
    db.session.add(trade)
    db.session.add(PricePoint(stock_id=stock.id, price=stock.price))
    db.session.commit()
    return True, trade
