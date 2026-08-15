import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE_PATH = os.getenv("DATABASE_PATH", os.path.join(BASE_DIR, "instance", "market.db"))
os.makedirs(os.path.dirname(os.path.abspath(DATABASE_PATH)), exist_ok=True)

SECRET_KEY = os.getenv("SECRET_KEY", "freshman-pump-and-dump-dev-key")
MODERATOR_USERNAME = os.getenv("MODERATOR_USERNAME", "trent")
MODERATOR_PASSWORD = os.getenv("MODERATOR_PASSWORD", "admin123")

MARKET_OPEN_HOUR = 12
MARKET_CLOSE_HOUR = 20
IPO_START = "2026-08-16T14:00:00-06:00"
IPO_END = "2026-08-16T18:00:00-06:00"
MARKET_TIMEZONE = "America/Denver"

STOCK_START_PRICE = 0.100
STOCK_SHARES = 300
MIN_PRICE = 0.001
MAX_TRADE_SHARES = 50
PRICE_STEP = 0.0003
