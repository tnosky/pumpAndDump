import os
from datetime import datetime, date

from dotenv import load_dotenv
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import desc

from auth import current_user, login_required, moderator_required
from config import (
    MODERATOR_PASSWORD,
    MODERATOR_USERNAME,
    STOCK_SHARES,
    STOCK_START_PRICE,
    MARKET_TIMEZONE,
    PRICE_STEP,
    MARKET_OPEN_HOUR,
    MARKET_CLOSE_HOUR,
    DAILY_SHARE_LIMIT,
    DAILY_SELL_LIMIT,
    INITIAL_GRANT_SHARES,
)
from market import change_from_start, daily_remaining, execute_trade, market_is_open
from analytics import stock_stats, user_holdings, user_realized_gain, user_stats, portfolio_history
from models import AuditLog, Holding, MarketSetting, PricePoint, Stock, Trade, User, ClosedDate, db
from extensions import socketio
from realtime import broadcast_market_update, market_payload

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "freshman-pump-and-dump-dev-key")
app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 24 * 30
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", f"sqlite:///{os.path.abspath('market.db')}")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)
socketio.init_app(app)

STOCKS = [
    ("ROB", "Reid O'Brien"),
    ("WIK", "Lukas Wik"),
    ("ZAR", "Zarien Rodriguez"),
    ("IVA", "Isaac Vasquez"),
    ("DWI", "David Williams"),
    ("MHA", "Miles Halvorsen"),
]


def _migrate_market_setting_columns():
    """Add new market_setting/user columns to an existing market.db without wiping data."""
    from sqlalchemy import inspect, text
    inspector = inspect(db.engine)
    with db.engine.begin() as conn:
        if "market_setting" in inspector.get_table_names():
            existing = {col["name"] for col in inspector.get_columns("market_setting")}
            additions = {
                "market_open_hour": f"INTEGER NOT NULL DEFAULT {MARKET_OPEN_HOUR}",
                "market_close_hour": f"INTEGER NOT NULL DEFAULT {MARKET_CLOSE_HOUR}",
                "daily_share_limit": f"INTEGER NOT NULL DEFAULT {DAILY_SHARE_LIMIT}",
                "daily_sell_limit": f"INTEGER NOT NULL DEFAULT {DAILY_SELL_LIMIT}",
            }
            for column, ddl in additions.items():
                if column not in existing:
                    conn.execute(text(f"ALTER TABLE market_setting ADD COLUMN {column} {ddl}"))
        if "user" in inspector.get_table_names():
            existing_user_cols = {col["name"] for col in inspector.get_columns("user")}
            if "starter_grant_cost" not in existing_user_cols:
                conn.execute(text("ALTER TABLE user ADD COLUMN starter_grant_cost FLOAT NOT NULL DEFAULT 0.0"))


def seed():
    with app.app_context():
        db.create_all()
        _migrate_market_setting_columns()
        if not MarketSetting.query.first():
            db.session.add(MarketSetting(market_enabled=True, note="Regular market hours"))
        if not User.query.filter_by(username=MODERATOR_USERNAME).first():
            db.session.add(User(
                username=MODERATOR_USERNAME,
                password=MODERATOR_PASSWORD,
                is_moderator=True,
                is_approved=True,
            ))
        for ticker, name in STOCKS:
            if not Stock.query.filter_by(ticker=ticker).first():
                stock = Stock(ticker=ticker, name=name, price=STOCK_START_PRICE, shares_outstanding=STOCK_SHARES)
                db.session.add(stock)
                db.session.flush()
                db.session.add(PricePoint(stock_id=stock.id, price=STOCK_START_PRICE))
        # clean up old null holdings
        db.session.execute(db.update(Holding).where(Holding.shares.is_(None)).values(shares=0))
        db.session.execute(db.update(Holding).where(Holding.avg_cost.is_(None)).values(avg_cost=0.0))
        db.session.commit()


@app.context_processor
def inject_globals():
    settings = MarketSetting.query.first()
    return {
        "current_user": current_user(),
        "market_open": market_is_open(settings) if settings else False,
        "stocks": Stock.query.order_by(Stock.id).all(),
        "now": datetime.now(),
        "price_step": PRICE_STEP,
        "market_timezone": MARKET_TIMEZONE,
    }


@app.route("/")
@login_required
def dashboard():
    recent_trades = Trade.query.order_by(desc(Trade.created_at)).limit(20).all()
    users = User.query.filter_by(is_approved=True, is_moderator=False).all()
    leaderboard = sorted(users, key=lambda u: u.net_worth(), reverse=True)
    return render_template("dashboard.html", recent_trades=recent_trades, leaderboard=leaderboard)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not username or not password:
            flash("Username and password are required.", "error")
            return render_template("register.html")
        if User.query.filter_by(username=username).first():
            flash("That username is already taken.", "error")
            return render_template("register.html")
        user = User(username=username, password=password)
        db.session.add(user)
        db.session.add(AuditLog(action="USER_REGISTERED", details=f"{username} registered"))
        db.session.commit()
        flash("Account created. A moderator must approve it before you can trade.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if not user or user.password != password:
            flash("Invalid username or password.", "error")
            return render_template("login.html")
        if not user.is_approved:
            flash("Your account is waiting for moderator approval.", "error")
            return render_template("login.html")
        session.permanent = True
        session["user_id"] = user.id
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/stock/<ticker>")
@login_required
def stock_page(ticker):
    stock = Stock.query.filter_by(ticker=ticker.upper()).first_or_404()
    points = PricePoint.query.filter_by(stock_id=stock.id).order_by(PricePoint.created_at).all()
    recent_trades = Trade.query.filter_by(stock_id=stock.id).order_by(desc(Trade.created_at)).limit(30).all()
    stats = stock_stats(stock)
    settings = MarketSetting.query.first()
    buy_remaining, buy_limit = daily_remaining(current_user().id, stock.id, settings, side="BUY")
    sell_remaining, sell_limit = daily_remaining(current_user().id, stock.id, settings, side="SELL")
    return render_template(
        "stock.html",
        stock=stock,
        points=points,
        recent_trades=recent_trades,
        stats=stats,
        daily_buy_remaining=buy_remaining,
        daily_buy_limit=buy_limit,
        daily_sell_remaining=sell_remaining,
        daily_sell_limit=sell_limit,
    )


@app.route("/trade", methods=["POST"])
@login_required
def trade():
    user = current_user()
    ticker = request.form.get("ticker", "").upper()
    side = request.form.get("side", "").upper()
    try:
        shares = int(request.form.get("shares", "0"))
    except ValueError:
        shares = 0
    stock = Stock.query.filter_by(ticker=ticker).first_or_404()
    ok, result = execute_trade(user, stock, side, shares, MarketSetting.query.first())
    wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in request.headers.get("Accept", "")
    if ok:
        broadcast_market_update(result)
        if wants_json:
            return jsonify({"ok": True, "trade": {
                "side": result.side,
                "ticker": stock.ticker,
                "shares": result.shares,
                "price": result.price,
                "total": result.total,
                "market_price": stock.price,
            }, "market": market_payload()})
        flash(f"{side.title()} {result.shares} {stock.ticker} at an average of ${result.price:.3f}.", "success")
    else:
        if wants_json:
            return jsonify({"ok": False, "error": result}), 400
        flash(result, "error")
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/portfolio")
@login_required
def portfolio():
    user = current_user()
    holdings = Holding.query.filter_by(user_id=user.id).join(Stock).order_by(Stock.ticker).all()
    history = portfolio_history(user)
    stats = user_stats(user)
    allocation = user_holdings(user)
    return render_template("portfolio.html", user=user, holdings=holdings, history=history, stats=stats, allocation=allocation)


@app.route("/leaderboard")
@login_required
def leaderboard():
    users = User.query.filter_by(is_approved=True, is_moderator=False).all()
    stats = {user.id: user_stats(user) for user in users}
    return render_template("leaderboard.html", users=users, stats=stats)


@app.route("/user/<username>")
@login_required
def user_profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    holdings = Holding.query.filter_by(user_id=user.id).join(Stock).order_by(Stock.ticker).all()
    trades = Trade.query.filter_by(user_id=user.id).order_by(desc(Trade.created_at)).limit(50).all()
    history = portfolio_history(user)
    stats = user_stats(user)
    allocation = user_holdings(user)
    return render_template("user.html", user=user, holdings=holdings, trades=trades, history=history, stats=stats, allocation=allocation)


@app.route("/moderator", methods=["GET", "POST"])
@moderator_required
def moderator():
    settings = MarketSetting.query.first()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "toggle_market":
            settings.market_enabled = not settings.market_enabled
            settings.note = "Manually toggled by moderator"
            db.session.add(AuditLog(actor_user_id=current_user().id, action="MARKET_TOGGLED", details=str(settings.market_enabled)))
            db.session.commit()
            socketio.emit("market_update", market_payload())
            flash(f"Market {'opened' if settings.market_enabled else 'closed'}.", "success")
        elif action == "approve":
            user = User.query.get_or_404(int(request.form["user_id"]))
            try:
                amount = float(request.form.get("starting_cash", "0"))
            except ValueError:
                amount = 0
            if 5 <= amount <= 20:
                user.is_approved = True
                user.starting_cash = round(amount, 2)
                user.cash = round(amount, 2)
                grant_cost = round(INITIAL_GRANT_SHARES * STOCK_START_PRICE * len(STOCKS), 2)
                granted = False
                if user.cash >= grant_cost:
                    for ticker, _ in STOCKS:
                        stock = Stock.query.filter_by(ticker=ticker).first()
                        holding = Holding.query.filter_by(user_id=user.id, stock_id=stock.id).first()
                        if holding:
                            old_value = (holding.shares or 0) * (holding.avg_cost or 0.0)
                            holding.shares = (holding.shares or 0) + INITIAL_GRANT_SHARES
                            holding.avg_cost = (old_value + INITIAL_GRANT_SHARES * STOCK_START_PRICE) / holding.shares
                        else:
                            db.session.add(Holding(
                                user_id=user.id,
                                stock_id=stock.id,
                                shares=INITIAL_GRANT_SHARES,
                                avg_cost=STOCK_START_PRICE,
                            ))
                    user.cash = round(user.cash - grant_cost, 2)
                    user.starter_grant_cost = grant_cost
                    granted = True
                db.session.add(AuditLog(actor_user_id=current_user().id, action="USER_APPROVED", details=f"{user.username}: ${amount:.2f}" + (f", granted {INITIAL_GRANT_SHARES}/stock (${grant_cost:.2f})" if granted else "")))
                db.session.commit()
                if granted:
                    flash(f"Approved {user.username} with ${amount:.2f} — granted {INITIAL_GRANT_SHARES} shares of each stock (${grant_cost:.2f}), ${user.cash:.2f} cash left.", "success")
                else:
                    flash(f"Approved {user.username} with ${amount:.2f} cash. Not enough to cover the {INITIAL_GRANT_SHARES}-share starter grant (${grant_cost:.2f}), so no starter shares were given.", "success")
            else:
                flash("Starting cash must be between $5 and $20.", "error")
        elif action == "reject":
            user = User.query.get_or_404(int(request.form["user_id"]))
            name = user.username
            db.session.delete(user)
            db.session.add(AuditLog(actor_user_id=current_user().id, action="USER_REJECTED", details=name))
            db.session.commit()
            flash(f"Rejected {name}.", "success")
        elif action == "update_user":
            user = User.query.get_or_404(int(request.form["user_id"]))
            if user.is_moderator:
                flash("The moderator account cannot be edited here.", "error")
                return redirect(url_for("moderator"))
            password = request.form.get("password", "")
            cash_raw = request.form.get("cash", "")
            try:
                cash = float(cash_raw)
            except ValueError:
                cash = None
            if password:
                user.password = password
            if cash is not None and cash >= 0:
                user.cash = round(cash, 2)
            db.session.add(AuditLog(actor_user_id=current_user().id, action="USER_UPDATED", details=user.username))
            db.session.commit()
            flash(f"Updated {user.username}.", "success")
        elif action == "update_settings":
            try:
                new_open = int(request.form.get("market_open_hour", ""))
                new_close = int(request.form.get("market_close_hour", ""))
                new_buy_limit = int(request.form.get("daily_share_limit", ""))
                new_sell_limit = int(request.form.get("daily_sell_limit", ""))
            except ValueError:
                flash("Market settings must be whole numbers.", "error")
                return redirect(url_for("moderator"))
            if not (0 <= new_open < new_close <= 24):
                flash("Open hour must be less than close hour, both between 0 and 24.", "error")
            elif new_buy_limit < 1:
                flash("Daily buy limit must be at least 1.", "error")
            elif new_sell_limit < 1:
                flash("Daily sell limit must be at least 1.", "error")
            else:
                settings.market_open_hour = new_open
                settings.market_close_hour = new_close
                settings.daily_share_limit = new_buy_limit
                settings.daily_sell_limit = new_sell_limit
                db.session.add(AuditLog(
                    actor_user_id=current_user().id,
                    action="SETTINGS_UPDATED",
                    details=f"hours {new_open}:00-{new_close}:00, daily buy limit {new_buy_limit}, daily sell limit {new_sell_limit}",
                ))
                db.session.commit()
                socketio.emit("market_update", market_payload())
                flash("Market settings updated.", "success")
        elif action == "add_closed_date":
            raw = request.form.get("closed_date", "")
            note = request.form.get("note", "").strip()
            try:
                closed_date = date.fromisoformat(raw)
            except ValueError:
                closed_date = None
            if closed_date is None:
                flash("Enter a valid date.", "error")
            elif ClosedDate.query.filter_by(day=closed_date).first():
                flash("That date is already closed.", "error")
            else:
                db.session.add(ClosedDate(day=closed_date, note=note))
                db.session.add(AuditLog(actor_user_id=current_user().id, action="CLOSED_DATE_ADDED", details=f"{closed_date}: {note}"))
                db.session.commit()
                flash("Closed date added.", "success")
        elif action == "remove_closed_date":
            item = ClosedDate.query.get_or_404(int(request.form["closed_id"]))
            db.session.delete(item)
            db.session.add(AuditLog(actor_user_id=current_user().id, action="CLOSED_DATE_REMOVED", details=str(item.day)))
            db.session.commit()
            flash("Closed date removed.", "success")
        return redirect(url_for("moderator"))
    pending = User.query.filter_by(is_approved=False, is_moderator=False).order_by(User.created_at).all()
    users = User.query.filter_by(is_approved=True, is_moderator=False).order_by(User.username).all()
    closed_dates = ClosedDate.query.order_by(ClosedDate.day).all()
    logs = AuditLog.query.order_by(desc(AuditLog.created_at)).limit(30).all()
    return render_template(
        "moderator.html",
        pending=pending,
        users=users,
        settings=settings,
        closed_dates=closed_dates,
        logs=logs,
        initial_grant_shares=INITIAL_GRANT_SHARES,
        initial_grant_cost=round(INITIAL_GRANT_SHARES * STOCK_START_PRICE * len(STOCKS), 2),
    )


@app.route("/api/market")
@login_required
def api_market():
    return jsonify(market_payload())


def market_open_value():
    settings = MarketSetting.query.first()
    return market_is_open(settings)


with app.app_context():
    seed()


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.errorhandler(404)
def not_found(error):
    return render_template("error.html", code=404, title="not found", message="that page does not exist."), 404


@app.errorhandler(500)
def server_error(error):
    db.session.rollback()
    return render_template("error.html", code=500, title="server error", message="something went wrong on the server."), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    socketio.run(app, host="0.0.0.0", port=port, debug=os.getenv("FLASK_DEBUG", "0") == "1", allow_unsafe_werkzeug=True)
