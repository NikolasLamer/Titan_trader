# main.py
import asyncio
import logging
import signal
from typing import Set

from titan.logger import setup_logging
from titan.config import config
from titan.exchange_connector import ExchangeConnector
from titan.data_handler import DataHandler
from titan.strategy_logic import TitanStrategy
from titan.portfolio_manager import PortfolioManager
from titan.order_executor import OrderExecutor
from titan.orchestrator import MasterOrchestrator

# Global set of running tasks for graceful shutdown
running_tasks: Set[asyncio.Task] = set()

def handle_shutdown(sig, loop):
    """Gracefully stop all running asyncio tasks."""
    logging.info(f"Received shutdown signal {sig.name}. Cancelling tasks...")
    for task in running_tasks:
        task.cancel()

async def main():
    """Initializes and runs all bot components as concurrent tasks."""
    setup_logging()
    logging.info(f"Initializing TitanGrid Bot in {config.MODE} mode...")

    # --- Initialize Queues ---
    market_data_q = asyncio.Queue()
    strategy_input_q = asyncio.Queue()
    signal_q = asyncio.Queue()
    order_q = asyncio.Queue()

    # --- Instantiate Modules ---
    # In a full multi-bot system, a BotManager would handle this part.
    # For now, we instantiate one set of components for our single symbol.
    connector = ExchangeConnector(symbols=config.SYMBOLS, output_queue=market_data_q)
    
    data_handler = DataHandler(
        input_queue=market_data_q,
        strategy_input_queue=strategy_input_q
    )
    
    portfolio_manager = PortfolioManager(
        symbol=config.SYMBOLS[0], 
        signal_queue=signal_q, 
        order_queue=order_q
    )
    
    strategy = TitanStrategy(
        symbol=config.SYMBOLS[0],
        input_queue=strategy_input_q,
        signal_queue=signal_q,
        portfolio_manager=portfolio_manager
    )
    
    order_executor = OrderExecutor(
        order_queue=order_q,
        connector=connector
    )
    
    orchestrator = MasterOrchestrator(bot_manager=None) # bot_manager is conceptual for now

    # --- Create and Track Tasks ---
    tasks_to_run = [
        orchestrator.run(), 
        connector.run(),
        data_handler.run(),
        strategy.run(),
        portfolio_manager.run(),
        order_executor.run()
    ]
    
    for coro in tasks_to_run:
        task = asyncio.create_task(coro)
        running_tasks.add(task)
        task.add_done_callback(running_tasks.discard)

    logging.info(f"Starting {len(running_tasks)} concurrent tasks...")
    
    # Keep the main function alive to wait for tasks
    try:
        await asyncio.gather(*running_tasks)
    except asyncio.CancelledError:
        logging.info("Main task group cancelled. Bot is shutting down.")

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_shutdown, sig, loop)

    try:
        loop.run_until_complete(main())
    finally:
        logging.info("Bot shutdown complete.")
        loop.close()
