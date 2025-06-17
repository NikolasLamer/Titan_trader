# titan/config.py
import os
from dotenv import load_dotenv

# Load environment variables from a .env file for local development
load_dotenv()

class Config:
    """
    Main configuration class loading settings from environment variables.
    """
    # Exchange Credentials
    API_KEY = os.getenv('BYBIT_API_KEY')
    API_SECRET = os.getenv('BYBIT_API_SECRET')
    WEBSOCKET_URL = "wss://stream.bybit.com/v5/public/spot" # Example for Bybit Spot

    # Strategy Parameters (from Pine Script inputs)
    TRADE_MODE = os.getenv('TRADE_MODE', 'Dual-Side')
    GRID_WIDTH_PCT = float(os.getenv('GRID_WIDTH_PCT', 1.0))
    SUPERTREND_PERIOD = int(os.getenv('SUPERTREND_PERIOD', 30))
    SUPERTREND_MULTIPLIER = float(os.getenv('SUPERTREND_MULTIPLIER', 3.0))
    MAX_ENTRIES = int(os.getenv('MAX_ENTRIES', 2))
    RISK_PCT_PER_TRADE = float(os.getenv('RISK_PCT_PER_TRADE', 1.0))
    INITIAL_CAPITAL = float(os.getenv('INITIAL_CAPITAL', 10000.0))

    # Bot Settings
    SYMBOLS = ["BTCUSDT", "ETHUSDT"] # Example symbols to trade

# Instantiate the config to be imported by other modules
config = Config()
