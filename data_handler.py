# titan/data_handler.py
import asyncio
import logging
import pandas as pd
import pandas_ta as ta
from titan.config import config

class DataHandler:
    """
    Consumes raw data, creates OHLCV bars, and calculates indicators.
    """
    def __init__(self, input_queue: asyncio.Queue, strategy_input_queue: asyncio.Queue):
        self.input_queue = input_queue
        self.strategy_input_queue = strategy_input_queue
        # Store data per symbol
        self.ticks = {symbol: [] for symbol in config.SYMBOLS}
        self.ohlc_data = {symbol: pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume']) for symbol in config.SYMBOLS}
        self.resample_period = '1T' # 1-minute bars

    def _process_tick(self, tick_data: dict):
        """Processes a single raw trade tick and appends it."""
        try:
            for trade in tick_data.get('data', []):
                symbol = trade['s']
                price = float(trade['p'])
                volume = float(trade['v'])
                timestamp = pd.to_datetime(trade['T'], unit='ms')
                self.ticks[symbol].append({'timestamp': timestamp, 'price': price, 'volume': volume})
        except (KeyError, ValueError) as e:
            logging.error(f"Error processing tick data: {tick_data}", exc_info=True)

    async def _resample_and_calculate_features(self):
        """Periodically resamples ticks to OHLC and calculates indicators."""
        while True:
            await asyncio.sleep(60) # Resample every 60 seconds
            for symbol in config.SYMBOLS:
                if not self.ticks[symbol]:
                    continue
                
                # Convert ticks to DataFrame and resample
                df_ticks = pd.DataFrame(self.ticks[symbol]).set_index('timestamp')
                self.ticks[symbol].clear() # Clear processed ticks
                
                ohlc = df_ticks['price'].resample(self.resample_period).ohlc()
                volume = df_ticks['volume'].resample(self.resample_period).sum()
                
                # Combine into one OHLCV DataFrame
                df_resampled = pd.concat([ohlc, volume], axis=1)
                df_resampled.columns = ['open', 'high', 'low', 'close', 'volume']
                
                # Append to historical data
                self.ohlc_data[symbol] = pd.concat([self.ohlc_data[symbol], df_resampled]).dropna()
                # Limit memory usage
                self.ohlc_data[symbol] = self.ohlc_data[symbol].tail(1000) 
                
                # --- Feature Engineering ---
                df_features = self.ohlc_data[symbol].copy()
                if len(df_features) > config.SUPERTREND_PERIOD:
                    df_features.ta.supertrend(
                        period=config.SUPERTREND_PERIOD,
                        multiplier=config.SUPERTREND_MULTIPLIER,
                        append=True
                    )
                    
                    # Pass the enriched DataFrame to the strategy
                    await self.strategy_input_queue.put({'symbol': symbol, 'data': df_features})
                    logging.info(f"Calculated features for {symbol}. Last close: {df_features['close'].iloc[-1]:.2f}")


    async def run(self):
        """Main run loop for the data handler."""
        logging.info("DataHandler is running.")
        # Start the periodic resampling task
        asyncio.create_task(self._resample_and_calculate_features())
        
        while True:
            raw_data = await self.input_queue.get()
            self._process_tick(raw_data)
            self.input_queue.task_done()
