from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config import MARKET_TIMEZONE, MARKET_OPEN_HOUR, MARKET_CLOSE_HOUR, MIN_PRICE, PRICE_STEP, DAILY_SHARE_LIMIT
from models import AuditLog, ClosedDate, Holding, PricePoint, Trade, db


def open_hour(settings):
    return settings.market_open_hour if settings and settings.market_open_hour is not None else MARKET_OPEN_HOUR


def close_hour(settings):
    return settings.market_close_hour if settings and settings.market_close_hour is not None else MARKET_CLOSE_HOUR


def daily_limit(settings):
    return settings.daily_share_limit if settings and settings.daily_share_limit else DAILY_SHARE_LIMIT


def market_is_open(settings):
    if not settings.market_enabled:
        return False
    now = datetime.now(ZoneInfo(MARKET_TIMEZONE))
    if now.weekday() == 6 or ClosedDate.query.filter_by(day=now.date()).first():
        return False
    return open_hour(settings) <= now.hour < close_hour(settings)


def market_day_bounds(now=None):
    """UTC datetime bounds for 'today' in the market's local timezone."""
    tz = ZoneInfo(MARKET_TIMEZONE)
    now = now or datetime.now(tz)
    start_local = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    end_utc = end_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    return start_utc, end_utc


def shares_bought_today(user_id, stock_id):
    start_utc, end_utc = market_day_bounds()
    total = db.session.query(db.func.coalesce(db.func.sum(Trade.shares), 0)).filter(
        Trade.user_id == user_id,
        Trade.stock_id == stock_id,
        Trade.side == "BUY",
        Trade.created_at >= start_utc,
        Trade.created_at < end_utc,
    ).scalar()
    return total or 0


def daily_remaining(user_id, stock_id, settings):
    limit = daily_limit(settings)
    bought = shares_bought_today(user_id, stock_id)
    return max(0, limit - bought), limit


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
        bought_today = shares_bought_today(user.id, stock.id)
        limit = daily_limit(settings)
        if bought_today + shares > limit:
            remaining = max(0, limit - bought_today)
            return False, (
                f"Daily purchase limit reached for {stock.ticker}: you can buy "
                f"{remaining} more share(s) today (limit {limit}/day)."
            )
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
