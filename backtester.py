# titan/backtester.py (Updated)
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
        # NEW: Define timeframes to test
        self.timeframes = [1, 5, 15] # In minutes

    def _fetch_historical_data(self, ticker: str, interval: int) -> pd.DataFrame:
        """Fetches historical data for a specific interval."""
        # 48 hours of data: 48 * 60 / interval = number of candles
        limit = int(48 * 60 / interval)
        try:
            response = self.http_session.get_kline(
                category="linear", symbol=ticker, interval=interval, limit=limit
            )
            if response and response.get('retCode') == 0:
                # ... (same data processing logic as before) ...
                data = response['result']['list']
                df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'turnover'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                df = df.set_index('timestamp').sort_index()
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df[col] = pd.to_numeric(df[col])
                return df
        except Exception as e:
            logging.error(f"Failed to fetch {interval}m data for {ticker}: {e}")
        return pd.DataFrame()

    def _run_single_backtest(self, data: pd.DataFrame, period: int, multiplier: float) -> dict:
        # ... (same implementation as before) ...
        if data.empty or len(data) < period:
            return {'net_profit': -100, 'win_rate': 0}
        df = data.copy()
        df.ta.supertrend(period=period, multiplier=multiplier, append=True)
        st_direction_col = f'SUPERTd_{period}_{multiplier}'
        df['position'] = np.where(df[st_direction_col] == 1, 1, -1)
        df['returns'] = df['close'].pct_change()
        df['strategy_returns'] = df['returns'] * df['position'].shift(1)
        cumulative_returns = (1 + df['strategy_returns']).cumprod()
        net_profit = (cumulative_returns.iloc[-1] - 1) * 100
        wins = df[df['strategy_returns'] > 0].shape[0]
        losses = df[df['strategy_returns'] < 0].shape[0]
        win_rate = (wins / (wins + losses)) * 100 if (wins + losses) > 0 else 0
        return {'net_profit': net_profit, 'win_rate': win_rate}

    async def run_optimization_for_ticker(self, ticker: str) -> dict | None:
        """Runs all parameter and timeframe combinations for a single ticker."""
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
            return None

        logging.info(f"Best params for {ticker}: {best_overall_params} -> Profit: {best_overall_performance['net_profit']:.2f}%")
        return {
            'ticker': ticker,
            'best_params': best_overall_params,
            'best_performance': best_overall_performance
        }
