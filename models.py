from datetime import datetime
from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(40), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    is_moderator = db.Column(db.Boolean, default=False, nullable=False)
    is_approved = db.Column(db.Boolean, default=False, nullable=False)
    starting_cash = db.Column(db.Float, default=0.0, nullable=False)
    cash = db.Column(db.Float, default=0.0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    holdings = db.relationship("Holding", backref="user", cascade="all, delete-orphan")
    trades = db.relationship("Trade", backref="user", cascade="all, delete-orphan")

    def portfolio_value(self):
        return sum((h.shares or 0) * h.stock.price for h in self.holdings)

    def net_worth(self):
        return self.cash + self.portfolio_value()

    def invested_value(self):
        return self.portfolio_value()

    def total_return(self):
        if self.starting_cash == 0:
            return 0.0
        return ((self.net_worth() - self.starting_cash) / self.starting_cash) * 100


class Stock(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ticker = db.Column(db.String(3), unique=True, nullable=False)
    name = db.Column(db.String(80), nullable=False)
    price = db.Column(db.Float, default=0.100, nullable=False)
    shares_outstanding = db.Column(db.Integer, default=300, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    holdings = db.relationship("Holding", backref="stock", cascade="all, delete-orphan")
    trades = db.relationship("Trade", backref="stock", cascade="all, delete-orphan")
    price_points = db.relationship("PricePoint", backref="stock", cascade="all, delete-orphan")

    def market_cap(self):
        # shares_outstanding is the original IPO baseline (300). Trading is
        # uncapped now, so once real demand pushes the actual float past that
        # baseline, market cap reflects the larger, real number of shares held.
        return self.price * max(self.shares_outstanding, self.shares_held())

    def shares_held(self):
        return sum((h.shares or 0) for h in self.holdings)

    def volume(self):
        return sum(t.shares for t in self.trades)

    def all_time_high(self):
        prices = [p.price for p in self.price_points]
        return max(prices + [self.price])

    def all_time_low(self):
        prices = [p.price for p in self.price_points]
        return min(prices + [self.price])


class Holding(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    stock_id = db.Column(db.Integer, db.ForeignKey("stock.id"), nullable=False)
    shares = db.Column(db.Integer, default=0, nullable=False)
    avg_cost = db.Column(db.Float, default=0.0, nullable=False)

    __table_args__ = (db.UniqueConstraint("user_id", "stock_id", name="uq_user_stock"),)


class Trade(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    stock_id = db.Column(db.Integer, db.ForeignKey("stock.id"), nullable=False)
    side = db.Column(db.String(4), nullable=False)
    shares = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)
    total = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class PricePoint(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    stock_id = db.Column(db.Integer, db.ForeignKey("stock.id"), nullable=False)
    price = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class MarketSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    market_enabled = db.Column(db.Boolean, default=True, nullable=False)
    note = db.Column(db.String(255), default="", nullable=False)
    market_open_hour = db.Column(db.Integer, default=12, nullable=False)
    market_close_hour = db.Column(db.Integer, default=20, nullable=False)
    daily_share_limit = db.Column(db.Integer, default=50, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class ClosedDate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    day = db.Column(db.Date, unique=True, nullable=False)
    note = db.Column(db.String(255), default="", nullable=False)


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    actor_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    action = db.Column(db.String(120), nullable=False)
    details = db.Column(db.String(500), default="", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    actor = db.relationship("User", foreign_keys=[actor_user_id])
