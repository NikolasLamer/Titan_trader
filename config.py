# titan/config.py
import os
from dotenv import load_dotenv
import logging

# Load environment variables from a .env file for local development
load_dotenv()

class Config:
    """Main configuration class loading settings from environment variables."""
    # --- Exchange Credentials ---
    API_KEY = os.getenv('BYBIT_API_KEY')
    API_SECRET = os.getenv('BYBIT_API_SECRET')
    
    # --- Bot Mode ---
    # Set to 'LIVE' to use real exchange connections
    MODE = os.getenv('MODE', 'SIMULATION') 

    # --- Endpoints ---
    WEBSOCKET_URL = "wss://stream.bybit.com/v5/public/spot"
    
    # --- Strategy Parameters ---
    SYMBOLS = ["BTCUSDT"] # Start with one symbol for simplicity
    TRADE_MODE = os.getenv('TRADE_MODE', 'Dual-Side')
    GRID_WIDTH_PCT = float(os.getenv('GRID_WIDTH_PCT', 1.0))
    SUPERTREND_PERIOD = int(os.getenv('SUPERTREND_PERIOD', 10)) # Smaller for faster signals in sim
    SUPERTREND_MULTIPLIER = float(os.getenv('SUPERTREND_MULTIPLIER', 3.0))
    MAX_ENTRIES = int(os.getenv('MAX_ENTRIES', 2))
    RISK_PCT_PER_TRADE = float(os.getenv('RISK_PCT_PER_TRADE', 1.0))
    INITIAL_CAPITAL = float(os.getenv('INITIAL_CAPITAL', 10000.0))
    LEVERAGE_MULTIPLIER = int(os.getenv('LEVERAGE_MULTIPLIER', 10))
    TAKER_FEE = float(os.getenv('TAKER_FEE', 0.0006)) # As fraction
    MAKER_FEE = float(os.getenv('MAKER_FEE', 0.0001)) # As fraction
    
    # --- Validation ---
    if not API_KEY or not API_SECRET:
        logging.warning("API_KEY or API_SECRET not found in environment variables.")

config = Config()
