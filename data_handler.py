# titan/data_handler.py (Updated for multi-bot routing)
import asyncio
import logging
import pandas as pd
import pandas_ta as ta
from titan.config import config

class DataHandler:
    def __init__(self, input_queue: asyncio.Queue):
        self.input_queue = input_queue
        # NEW: A dictionary to map symbols to their dedicated strategy queues
        self.strategy_queues: Dict[str, asyncio.Queue] = {}
        # ... (rest of __init__ is the same) ...
        self.ticks = {}
        self.ohlc_data = {}
        self.resample_period = '1T'

    def register_strategy_queue(self, symbol: str, queue: asyncio.Queue):
        """Allows the BotManager to register a new symbol and its queue."""
        logging.info(f"DATA HANDLER: Registering strategy queue for {symbol}")
        self.strategy_queues[symbol] = queue
        self.ticks[symbol] = []
        self.ohlc_data[symbol] = pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume'])

    def deregister_strategy_queue(self, symbol: str):
        """Allows the BotManager to deregister a symbol."""
        logging.info(f"DATA HANDLER: Deregistering strategy queue for {symbol}")
        self.strategy_queues.pop(symbol, None)
        self.ticks.pop(symbol, None)
        self.ohlc_data.pop(symbol, None)

    async def _resample_and_calculate_features(self):
        """Periodically resamples ticks and calculates indicators for all registered symbols."""
        while True:
            await asyncio.sleep(60)
            
            # Loop through only the symbols we are actively managing
            for symbol in list(self.strategy_queues.keys()):
                # ... (resampling logic is the same) ...
                if not self.ticks.get(symbol): continue
                
                # --- Feature Engineering ---
                df_features = self.ohlc_data[symbol].copy()
                if len(df_features) > config.SUPERTREND_PERIOD:
                    # ... (supertrend calculation is the same) ...
                    
                    # NEW: Route the enriched data to the correct queue
                    if symbol in self.strategy_queues:
                        output_payload = {'symbol': symbol, 'data': df_features}
                        await self.strategy_queues[symbol].put(output_payload)
                        logging.info(f"Calculated features for {symbol}. Pushed to its dedicated queue.")

    # ... (run and _process_tick methods are mostly the same) ...
