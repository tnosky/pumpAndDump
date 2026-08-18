from datetime import datetime
from zoneinfo import ZoneInfo

from config import (
    MARKET_TIMEZONE,
    MARKET_OPEN_HOUR,
    MARKET_CLOSE_HOUR,
    MIN_PRICE,
    PRICE_STEP,
    STOCK_START_PRICE,
    IPO_START,
    IPO_END,
)
from models import AuditLog, ClosedDate, Holding, IPOOrder, MarketSetting, MarketState, PricePoint, Trade, User, db

IPO_MIN_PRICE = 0.075
IPO_MAX_PRICE = 0.150


def ipo_window():
    start = datetime.fromisoformat(IPO_START)
    end = datetime.fromisoformat(IPO_END)
    return start, end


def ipo_is_active():
    start, end = ipo_window()
    now = datetime.now(ZoneInfo(MARKET_TIMEZONE))
    return start <= now < end


def ipo_seconds_remaining():
    _, end = ipo_window()
    now = datetime.now(ZoneInfo(MARKET_TIMEZONE))
    return max(0, int((end - now).total_seconds()))


def maybe_complete_ipo():
    state = get_market_state()
    if not state or state.phase != "IPO":
        return False
    start, end = ipo_window()
    now = datetime.now(ZoneInfo(MARKET_TIMEZONE))
    if now < end:
        return False
    ok, _ = complete_ipo(allow_missing=True)
    return ok


def market_is_open(settings, state=None):
    state = state or MarketState.query.first()
    if not settings or not settings.market_enabled or not state or state.phase != "OPEN":
        return False
    now = datetime.now(ZoneInfo(MARKET_TIMEZONE))
    if now.weekday() == 4 or ClosedDate.query.filter_by(day=now.date()).first():
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


def get_market_state():
    return MarketState.query.first()


def ipo_price_for_demand(demand, shares_available=300):
    if demand <= 0:
        return IPO_MIN_PRICE
    ratio = demand / max(shares_available, 1)
    price = STOCK_START_PRICE * (0.75 + 0.25 * ratio)
    return max(IPO_MIN_PRICE, min(IPO_MAX_PRICE, price))


def user_ipo_requests(user):
    return {order.stock_id: order.shares for order in IPOOrder.query.filter_by(user_id=user.id).all()}


def ipo_status():
    state = get_market_state()
    users = User.query.filter_by(is_approved=True, is_moderator=False).all()
    stocks = StockProxy.all()
    submissions = {user.id: sum((order.shares or 0) for order in user.ipo_orders) for user in users}
    return {
        "phase": state.phase if state else "OPEN",
        "participants": len(users),
        "submitted": sum(1 for value in submissions.values() if value > 0),
        "all_submitted": all(value > 0 for value in submissions.values()) if users else False,
    }


class StockProxy:
    @staticmethod
    def all():
        from models import Stock
        return Stock.query.order_by(Stock.id).all()


def save_ipo_order(user, stock, shares):
    state = get_market_state()
    if not state or state.phase != "IPO":
        return False, "The IPO phase is closed."
    if not ipo_is_active():
        start, end = ipo_window()
        now = datetime.now(ZoneInfo(MARKET_TIMEZONE))
        if now < start:
            return False, "The IPO has not opened yet. It opens August 16 at 2:00 PM MDT."
        return False, "The IPO phase ended at 4:00 PM MDT."
    if shares < 0:
        return False, "IPO requests cannot be negative."
    order = IPOOrder.query.filter_by(user_id=user.id, stock_id=stock.id).first()
    if not order:
        order = IPOOrder(user_id=user.id, stock_id=stock.id, shares=shares)
        db.session.add(order)
    else:
        order.shares = shares
    db.session.commit()
    return True, order


def complete_ipo(allow_missing=False):
    state = get_market_state()
    if not state or state.phase != "IPO":
        return False, "The IPO phase is already closed."

    users = User.query.filter_by(is_approved=True, is_moderator=False).all()
    if not users:
        return False, "At least one approved user is required."

    missing = [user.username for user in users if sum((o.shares or 0) for o in user.ipo_orders) <= 0]
    if missing and not allow_missing:
        return False, "Every approved user must submit at least one IPO request: " + ", ".join(missing)

    market_cash_added = 0.0
    ipo_results = []

    for stock in StockProxy.all():
        orders = IPOOrder.query.filter_by(stock_id=stock.id).all()
        demand = sum(max(order.shares, 0) for order in orders)
        price = ipo_price_for_demand(demand, stock.shares_outstanding)
        allocations = {}
        if demand <= stock.shares_outstanding:
            allocations = {order.user_id: order.shares for order in orders}
        elif demand > 0:
            scale = stock.shares_outstanding / demand
            raw = {order.user_id: order.shares * scale for order in orders}
            allocations = {user_id: int(value) for user_id, value in raw.items()}
            used = sum(allocations.values())
            remainder = stock.shares_outstanding - used
            ranked = sorted(raw.items(), key=lambda item: item[1] - int(item[1]), reverse=True)
            for user_id, _ in ranked[:remainder]:
                allocations[user_id] += 1

        for user in users:
            requested = next((o.shares for o in orders if o.user_id == user.id), 0)
            allocated = allocations.get(user.id, 0)
            if requested > 0 and allocated == 0 and stock.shares_outstanding > 0:
                allocated = 1 if sum(allocations.values()) < stock.shares_outstanding else 0
            if allocated <= 0:
                continue
            allocations[user.id] = allocated

        for user in users:
            allocated = allocations.get(user.id, 0)
            if not allocated:
                continue
            holding = Holding.query.filter_by(user_id=user.id, stock_id=stock.id).first()
            if not holding:
                holding = Holding(user_id=user.id, stock_id=stock.id, shares=0, avg_cost=0.0)
                db.session.add(holding)
                db.session.flush()
            old_value = (holding.shares or 0) * (holding.avg_cost or 0.0)
            cost = allocated * price
            if cost > user.cash:
                affordable = int(user.cash // price)
                allocated = min(allocated, affordable)
                cost = allocated * price
            if allocated <= 0:
                continue
            user.cash -= cost
            market_cash_added += cost
            holding.shares = (holding.shares or 0) + allocated
            holding.avg_cost = (old_value + cost) / holding.shares
            trade = Trade(
                user_id=user.id,
                stock_id=stock.id,
                side="IPO",
                shares=allocated,
                price=price,
                total=cost,
                created_at=datetime.utcnow(),
            )
            db.session.add(trade)
            ipo_results.append({"username": user.username, "ticker": stock.ticker, "requested": next((o.shares for o in orders if o.user_id == user.id), 0), "allocated": allocated, "price": price, "total": cost})

        stock.price = price
        db.session.add(PricePoint(stock_id=stock.id, price=price))

    state.market_cash += market_cash_added
    state.phase = "OPEN"
    state.ipo_completed_at = datetime.utcnow()
    state.updated_at = datetime.utcnow()
    db.session.add(AuditLog(action="IPO_COMPLETED", details=f"market cash funded: ${market_cash_added:.2f}"))
    db.session.commit()
    return True, ipo_results


def execute_trade(user, stock, side, shares, settings):
    state = get_market_state()
    if state and state.phase == "IPO":
        return False, "The IPO phase is active. Finish your IPO allocation before normal trading begins."
    if not market_is_open(settings, state):
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

    market_cash = state.market_cash

    if side == "BUY":
        if stock.shares_available() < shares:
            return False, "There are not enough shares available."
        total = 0.0
        for _ in range(shares):
            price = stock.price
            total += price
            stock.price = max(stock.price + PRICE_STEP, MIN_PRICE)
        if user.cash < total:
            db.session.rollback()
            return False, f"You need {format_money(total)}."
        user.cash -= total
        state.market_cash = market_cash + total
        if holding is None:
            holding = Holding(user_id=user.id, stock_id=stock.id, shares=0, avg_cost=0.0)
            db.session.add(holding)
            db.session.flush()
        old_value = (holding.shares or 0) * (holding.avg_cost or 0.0)
        holding.shares = (holding.shares or 0) + shares
        holding.avg_cost = (old_value + total) / holding.shares
    else:
        if holding is None or (holding.shares or 0) < shares:
            return False, "You do not own enough shares."
        total = 0.0
        for _ in range(shares):
            next_price = max(MIN_PRICE, stock.price - PRICE_STEP)
            total += next_price
            stock.price = next_price
        if state.market_cash < total:
            db.session.rollback()
            return False, "The market does not currently have enough cash to buy those shares."
        state.market_cash -= total
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
