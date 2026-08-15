import os
from datetime import datetime, date

from dotenv import load_dotenv
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import desc

from auth import current_user, login_required, moderator_required
from config import DATABASE_PATH, MODERATOR_PASSWORD, MODERATOR_USERNAME, STOCK_SHARES, STOCK_START_PRICE, MARKET_TIMEZONE, PRICE_STEP
from market import change_from_start, execute_trade, market_is_open, complete_ipo, get_market_state, ipo_status, save_ipo_order, ipo_is_active, maybe_complete_ipo
from analytics import stock_stats, user_holdings, user_realized_gain, user_stats, portfolio_history
from models import AuditLog, Holding, MarketSetting, MarketState, PricePoint, Stock, Trade, User, ClosedDate, IPOOrder, db
from extensions import socketio
from realtime import broadcast_market_update, market_payload

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "freshman-pump-and-dump-dev-key")
app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 24 * 30
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.path.abspath(DATABASE_PATH)}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)
socketio.init_app(app)

STOCKS = [
    ("ROB", "Reid O'Brien"),
    ("WIK", "Lukas Wik"),
    ("ZROD", "Zarien Rodriguez"),
    ("IVAS", "Isaac Vasquez"),
    ("DWIL", "David Williams"),
    ("HAL", "Miles Halvorsen"),
]


def seed():
    with app.app_context():
        db.create_all()
        if not MarketSetting.query.first():
            db.session.add(MarketSetting(market_enabled=True, note="Regular market hours"))
        state = MarketState.query.first()
        if not state:
            existing_trade = Trade.query.first()
            approved_users = User.query.filter_by(is_approved=True, is_moderator=False).all()
            inferred_market_cash = sum(max(u.starting_cash, 0.0) - max(u.cash, 0.0) for u in approved_users)
            state = MarketState(phase="OPEN" if existing_trade else "IPO", market_cash=max(0.0, inferred_market_cash))
            db.session.add(state)
        if not User.query.filter_by(username=MODERATOR_USERNAME).first():
            db.session.add(User(
                username=MODERATOR_USERNAME,
                password=MODERATOR_PASSWORD,
                is_moderator=True,
                is_approved=True,
            ))
        legacy_tickers = {"ZAR": "ZROD", "IVA": "IVAS", "DWI": "DWIL", "MHA": "HAL"}
        for old_ticker, new_ticker in legacy_tickers.items():
            legacy_stock = Stock.query.filter_by(ticker=old_ticker).first()
            if legacy_stock and not Stock.query.filter_by(ticker=new_ticker).first():
                legacy_stock.ticker = new_ticker

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
    maybe_complete_ipo()
    settings = MarketSetting.query.first()
    state = get_market_state() or MarketState(phase="OPEN", market_cash=0.0)
    return {
        "current_user": current_user(),
        "market_open": market_is_open(settings, state) if settings else False,
        "market_phase": state.phase,
        "market_cash": state.market_cash,
        "ipo_status": ipo_status(),
        "ipo_active": ipo_is_active(),
        "stocks": Stock.query.order_by(Stock.id).all(),
        "now": datetime.now(),
        "price_step": PRICE_STEP,
    }


@app.route("/")
@login_required
def dashboard():
    recent_trades = Trade.query.order_by(desc(Trade.created_at)).limit(20).all()
    users = User.query.filter_by(is_approved=True, is_moderator=False).all()
    leaderboard = sorted(users, key=lambda u: u.net_worth(), reverse=True)
    return render_template("dashboard.html", recent_trades=recent_trades, leaderboard=leaderboard, ipo=ipo_status(), state=get_market_state())


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
        flash("Account created. Trent must approve it before you can trade.", "success")
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
            flash("Your account is waiting for trent approval.", "error")
            return render_template("login.html")
        session.permanent = True
        session["user_id"] = user.id
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/ipo")
@login_required
def ipo_page():
    state = get_market_state()
    if not state or state.phase != "IPO":
        return redirect(url_for("dashboard"))
    orders = {order.stock_id: order.shares for order in IPOOrder.query.filter_by(user_id=current_user().id).all()}
    stocks = Stock.query.order_by(Stock.id).all()
    demand = {}
    for stock in stocks:
        demand[stock.id] = sum((o.shares or 0) for o in IPOOrder.query.filter_by(stock_id=stock.id).all())
    return render_template("ipo.html", stocks=stocks, orders=orders, demand=demand, ipo=ipo_status(), state=state)


@app.route("/ipo/order", methods=["POST"])
@login_required
def ipo_order():
    ticker = request.form.get("ticker", "").upper()
    try:
        shares = int(request.form.get("shares", "0"))
    except ValueError:
        shares = -1
    stock = Stock.query.filter_by(ticker=ticker).first_or_404()
    ok, result = save_ipo_order(current_user(), stock, shares)
    wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in request.headers.get("Accept", "")
    if wants_json:
        return jsonify({"ok": ok, "error": None if ok else result, "ticker": ticker, "shares": shares}) if ok else (jsonify({"ok": False, "error": result}), 400)
    flash(f"IPO request updated: {shares} {ticker}." if ok else result, "success" if ok else "error")
    return redirect(url_for("ipo_page"))


@app.route("/stock/<ticker>")
@login_required
def stock_page(ticker):
    stock = Stock.query.filter_by(ticker=ticker.upper()).first_or_404()
    points = PricePoint.query.filter_by(stock_id=stock.id).order_by(PricePoint.created_at).all()
    recent_trades = Trade.query.filter_by(stock_id=stock.id).order_by(desc(Trade.created_at)).limit(30).all()
    stats = stock_stats(stock)
    return render_template("stock.html", stock=stock, points=points, recent_trades=recent_trades, stats=stats, state=get_market_state())


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
        if action == "close_ipo":
            ok, result = complete_ipo()
            if ok:
                db.session.add(AuditLog(actor_user_id=current_user().id, action="IPO_CLOSED", details="IPO allocations finalized and market opened"))
                db.session.commit()
                broadcast_market_update()
                flash("IPO closed. Allocations are final and normal trading is open.", "success")
            else:
                flash(result, "error")
        elif action == "toggle_market":
            settings.market_enabled = not settings.market_enabled
            settings.note = "Manually toggled by trent"
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
                db.session.add(AuditLog(actor_user_id=current_user().id, action="USER_APPROVED", details=f"{user.username}: ${amount:.2f}"))
                db.session.commit()
                flash(f"Approved {user.username} with ${amount:.2f}.", "success")
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
                flash("trent account cannot be edited here.", "error")
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
    return render_template("moderator.html", pending=pending, users=users, settings=settings, closed_dates=closed_dates, logs=logs, state=get_market_state(), ipo=ipo_status())


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
