# titan/orchestrator.py
import asyncio
import logging
import aiohttp
import pandas as pd
from typing import Set

# Import pybit for exchange-specific interaction
from pybit.unified_trading import HTTP

from titan.config import config
from titan.backtester import VectorizedBacktester
# from titan.bot_manager import BotManager

class MasterOrchestrator:
    """
    The master controller that performs the 15-minute analysis and optimization cycle.
    Includes verification of tradable symbols against the target exchange.
    """
    def __init__(self, bot_manager):
        self.fetch_url = "https://scalpstation.com/kapi/binance/futures/kdata?top=25&interval=5m&Delta5m"
        self.backtester = VectorizedBacktester()
        self.bot_manager = bot_manager
        self.current_top_5_tokens = set()

        # Initialize the synchronous pybit HTTP client for REST API calls
        # This will be used for fetching instrument info and later, for placing orders
        self.bybit_session = HTTP(
            testnet=False, 
            api_key=config.API_KEY, 
            api_secret=config.API_SECRET
        )
        self.tradable_symbols: Set[str] = set()

    async def fetch_tradable_bybit_symbols(self, category="spot") -> None:
        """
        Fetches all tradable symbols from Bybit for a given category.
        This is a synchronous call wrapped in an executor to be non-blocking.
        """
        logging.info(f"Fetching all tradable symbols for category: {category}...")
        loop = asyncio.get_running_loop()
        try:
            # Run the synchronous pybit call in a thread pool executor
            response = await loop.run_in_executor(
                None,  # Use the default executor
                lambda: self.bybit_session.get_instruments_info(category=category)
            )
            
            if response and response.get('retCode') == 0:
                symbols = {item['symbol'] for item in response['result']['list']}
                self.tradable_symbols = symbols
                logging.info(f"Successfully fetched {len(self.tradable_symbols)} tradable symbols from Bybit.")
            else:
                logging.error(f"Failed to fetch symbols from Bybit: {response.get('retMsg')}")
                # Keep the old set of symbols if the new fetch fails
                if not self.tradable_symbols:
                    self.tradable_symbols = set()
        except Exception as e:
            logging.error(f"Exception while fetching Bybit symbols: {e}", exc_info=True)

    async def fetch_top_tokens(self) -> list[str]:
        """Fetches the list of top 25 performing tokens from the external API."""
        # ... (implementation from previous response remains the same) ...
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.fetch_url) as response:
                    response.raise_for_status()
                    data = await response.json()
                    tickers = [item['s'] for item in data.get('d', []) if 's' in item]
                    logging.info(f"Fetched {len(tickers)} candidate tokens.")
                    return tickers[:25]
        except Exception as e:
            logging.error(f"Failed to fetch top tokens: {e}", exc_info=True)
            return []


    async def run_optimization_cycle(self):
        """The main periodic task for the orchestrator."""
        logging.info("--- Starting New Optimization & Selection Cycle ---")
        
        # Step 1: Refresh the list of tradable symbols from Bybit
        # We target the 'linear' category for USDT perpetuals, adjust if using Spot or Inverse
        await self.fetch_tradable_bybit_symbols(category="linear")
        if not self.tradable_symbols:
            logging.error("Could not fetch tradable symbols from Bybit. Halting cycle.")
            return

        # Step 2: Fetch top candidate tokens
        candidate_tokens = await self.fetch_top_tokens()
        if not candidate_tokens:
            logging.warning("Halting cycle due to failure in fetching candidate tokens.")
            return

        # Step 3: Filter candidates to only those tradable on Bybit
        valid_tokens_to_backtest = [
            ticker for ticker in candidate_tokens if ticker in self.tradable_symbols
        ]
        logging.info(f"Validated {len(valid_tokens_to_backtest)}/{len(candidate_tokens)} tokens are tradable on Bybit.")

        if not valid_tokens_to_backtest:
            logging.warning("No valid tradable tokens found after filtering. Halting cycle.")
            return

        # Step 4: Run backtests on the filtered list concurrently
        backtest_tasks = [self.backtester.run_optimization_for_ticker(ticker) for ticker in valid_tokens_to_backtest]
        results = await asyncio.gather(*backtest_tasks)
        
        successful_results = [res for res in results if res]

        # Step 5: Rank results and select the new top 5 from the valid pool
        successful_results.sort(key=lambda x: x['best_performance']['net_profit'], reverse=True)
        new_top_5 = {res['ticker']: res['best_params'] for res in successful_results[:5]}
        new_top_5_tickers = set(new_top_5.keys())
        
        logging.info(f"New Top 5 Selected: {list(new_top_5_tickers)}")
        
        # Step 6: Reconcile with currently running bots
        tokens_to_start = new_top_5_tickers - self.current_top_5_tokens
        tokens_to_stop = self.current_top_5_tokens - new_top_5_tickers
        
        for ticker in tokens_to_start:
            params = new_top_5[ticker]
            # self.bot_manager.start_bot(ticker, params)
            logging.info(f"COMMAND: Start bot for {ticker} with params {params}")


        for ticker in tokens_to_stop:
            # self.bot_manager.stop_bot(ticker)
            logging.info(f"COMMAND: Stop bot for {ticker} and manage existing position.")

        self.current_top_5_tokens = new_top_5_tickers

    async def run(self):
        """Runs the optimization cycle every 15 minutes."""
        while True:
            await self.run_optimization_cycle()
            logging.info("--- Cycle Complete. Waiting 15 minutes for next run. ---")
            await asyncio.sleep(15 * 60)
