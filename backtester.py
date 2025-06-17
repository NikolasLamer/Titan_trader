# titan/backtester.py
import logging
import pandas as pd
import pandas_ta as ta
import numpy as np
from pybit.unified_trading import HTTP

class VectorizedBacktester:
    def __init__(self):
        self.http_session = HTTP(testnet=False)
        self.param_grid = {
            'period': [20, 30, 40],
            'multiplier': [2.0, 2.5, 3.0, 3.5, 4.0]
        }
        self.timeframes = [1, 5, 15]
        self.data_cache = {} # Cache format: {(ticker, tf): df}

    def _fetch_historical_data(self, ticker: str, interval: int) -> pd.DataFrame:
        """Fetches historical data, using a cache to get only new candles."""
        cache_key = (ticker, interval)
        
        since_timestamp = 0
        # If we have cached data, fetch only new data since the last timestamp
        if cache_key in self.data_cache:
            last_timestamp_ms = int(self.data_cache[cache_key].index[-1].timestamp() * 1000)
            since_timestamp = last_timestamp_ms + 1 # +1 to avoid fetching the same candle

        # Fetch full history first time, then smaller updates
        limit = int(48 * 60 / interval) if since_timestamp == 0 else 200

        try:
            response = self.http_session.get_kline(
                category="linear",
                symbol=ticker,
                interval=interval,
                limit=limit,
                start=since_timestamp if since_timestamp > 0 else None
            )
            if response and response.get('retCode') == 0 and response['result']['list']:
                data = response['result']['list']
                new_df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'turnover'])
                new_df['timestamp'] = pd.to_datetime(new_df['timestamp'], unit='ms')
                new_df = new_df.set_index('timestamp').sort_index()
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    new_df[col] = pd.to_numeric(new_df[col])

                if cache_key in self.data_cache:
                    # Append new data, remove duplicates, and keep the tail
                    combined_df = pd.concat([self.data_cache[cache_key], new_df])
                    combined_df = combined_df[~combined_df.index.duplicated(keep='last')]
                    self.data_cache[cache_key] = combined_df.tail(limit)
                else:
                    self.data_cache[cache_key] = new_df
                
                return self.data_cache[cache_key]
            
            elif cache_key in self.data_cache:
                # If API returns no new data, return the existing cached version
                return self.data_cache[cache_key]

        except Exception as e:
            logging.error(f"Failed to fetch {interval}m data for {ticker}: {e}")
        
        return pd.DataFrame()

    def _run_single_backtest(self, data: pd.DataFrame, period: int, multiplier: float) -> dict:
        if data.empty or len(data) < period:
            return {'net_profit': -100, 'win_rate': 0}
        df = data.copy()
        df.ta.supertrend(period=period, multiplier=multiplier, append=True)
        st_direction_col = f'SUPERTd_{period}_{multiplier}'
        
        # Ensure the column exists before proceeding
        if st_direction_col not in df.columns:
            return {'net_profit': -100, 'win_rate': 0}
            
        df['position'] = np.where(df[st_direction_col] == 1, 1, -1)
        df['returns'] = df['close'].pct_change()
        df['strategy_returns'] = df['returns'] * df['position'].shift(1)
        
        # Drop NaNs to ensure clean calculation
        df.dropna(subset=['strategy_returns'], inplace=True)
        if df.empty:
            return {'net_profit': 0, 'win_rate': 0}

        cumulative_returns = (1 + df['strategy_returns']).cumprod()
        net_profit = (cumulative_returns.iloc[-1] - 1) * 100 if not cumulative_returns.empty else 0
        
        wins = df[df['strategy_returns'] > 0].shape[0]
        losses = df[df['strategy_returns'] < 0].shape[0]
        win_rate = (wins / (wins + losses)) * 100 if (wins + losses) > 0 else 0
        
        return {'net_profit': net_profit, 'win_rate': win_rate}

    async def run_optimization_for_ticker(self, ticker: str) -> dict | None:
        logging.info(f"Starting full optimization for {ticker} across all timeframes...")
        
        best_overall_performance = {'net_profit': -101}
        best_overall_params = {}

        for timeframe in self.timeframes:
            historical_data = self._fetch_historical_data(ticker, timeframe)
            if historical_data.empty:
                logging.warning(f"No {timeframe}m data for {ticker}, skipping this timeframe.")
                continue

            for period in self.param_grid['period']:
                for multiplier in self.param_grid['multiplier']:
                    performance = self._run_single_backtest(historical_data, period, multiplier)
                    
                    if performance['net_profit'] > best_overall_performance.get('net_profit', -101):
                        best_overall_performance = performance
                        best_overall_params = {
                            'timeframe': timeframe,
                            'period': period, 
                            'multiplier': multiplier
                        }
        
        if not best_overall_params:
            logging.warning(f"No profitable parameters found for {ticker}.")
            return None

        logging.info(f"Best params for {ticker}: {best_overall_params} -> Profit: {best_overall_performance['net_profit']:.2f}%")
        return {
            'ticker': ticker,
            'best_params': best_overall_params,
            'best_performance': best_overall_performance
        }
