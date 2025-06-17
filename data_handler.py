# titan/data_handler.py
import asyncio
import logging
import pandas as pd
import pandas_ta as ta
from typing import Dict
from titan.config import config
from titan.datastructures import PriceUpdate

class DataHandler:
    def __init__(self, input_queue: asyncio.Queue):
        self.input_queue = input_queue
        self.strategy_queues: Dict[str, asyncio.Queue] = {}
        # NEW: A queue for each symbol to send price updates to its PortfolioManager
        self.price_update_queues: Dict[str, asyncio.Queue] = {}
        self.ticks: Dict[str, list] = {}
        self.ohlc_data: Dict[str, pd.DataFrame] = {}
        self.resample_period = '1T' # 1 Minute

    def register_bot_queues(self, symbol: str, strategy_q: asyncio.Queue, price_q: asyncio.Queue):
        """Allows the BotManager to register all necessary queues for a new symbol."""
        logging.info(f"DATA HANDLER: Registering queues for {symbol}")
        self.strategy_queues[symbol] = strategy_q
        self.price_update_queues[symbol] = price_q
        self.ticks[symbol] = []
        self.ohlc_data[symbol] = pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume'])

    def deregister_bot_queues(self, symbol: str):
        """Allows the BotManager to deregister a symbol."""
        logging.info(f"DATA HANDLER: Deregistering queues for {symbol}")
        self.strategy_queues.pop(symbol, None)
        self.price_update_queues.pop(symbol, None)
        self.ticks.pop(symbol, None)
        self.ohlc_data.pop(symbol, None)

    async def _process_tick(self, tick_data: dict):
        """Processes a single tick from the WebSocket."""
        try:
            topic = tick_data.get('topic', '')
            symbol = topic.split('.')[-1]

            if symbol in self.ticks:
                for trade in tick_data.get('data', []):
                    price = float(trade['p'])
                    self.ticks[symbol].append(price)
                    # NEW: Immediately push the latest price for real-time updates
                    if symbol in self.price_update_queues:
                        await self.price_update_queues[symbol].put(PriceUpdate(symbol=symbol, price=price))

        except Exception as e:
            logging.error(f"Error processing tick: {tick_data}. Error: {e}", exc_info=True)

    async def _resample_and_calculate_features(self):
        """Periodically resamples ticks and calculates indicators for all registered symbols."""
        while True:
            await asyncio.sleep(60) # Runs every minute
            
            for symbol in list(self.strategy_queues.keys()):
                if not self.ticks.get(symbol):
                    continue

                # Resample ticks into a 1-minute OHLC bar
                series = pd.Series(self.ticks[symbol])
                self.ticks[symbol] = [] # Clear the ticks buffer
                
                if series.empty:
                    continue

                ohlc = series.resample('1T').ohlc()
                if ohlc.empty:
                    continue
                
                # Append the new bar to the historical data
                self.ohlc_data[symbol] = pd.concat([self.ohlc_data[symbol], ohlc])
                # Keep a fixed window of data to prevent memory issues
                self.ohlc_data[symbol] = self.ohlc_data[symbol].tail(500)

                # --- Feature Engineering ---
                df_features = self.ohlc_data[symbol].copy()
                if len(df_features) > config.SUPERTREND_PERIOD:
                    df_features.ta.supertrend(
                        period=config.SUPERTREND_PERIOD,
                        multiplier=config.SUPERTREND_MULTIPLIER,
                        append=True
                    )
                    
                    if symbol in self.strategy_queues:
                        output_payload = {'symbol': symbol, 'data': df_features}
                        await self.strategy_queues[symbol].put(output_payload)
                        logging.info(f"Calculated features for {symbol} and pushed to its strategy queue.")

    async def run(self):
        """Main loop to process incoming ticks and periodically resample."""
        logging.info("DataHandler is running.")
        resample_task = asyncio.create_task(self._resample_and_calculate_features())
        
        while True:
            tick = await self.input_queue.get()
            await self._process_tick(tick)
            self.input_queue.task_done()
