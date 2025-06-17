# main.py
import asyncio
import logging
import signal
from typing import Set

from titan.logger import setup_logging
from titan.config import config
from titan.exchange_connector import ExchangeConnector
from titan.data_handler import DataHandler
from titan.orchestrator import MasterOrchestrator
from titan.bot_manager import BotManager

running_tasks: Set[asyncio.Task] = set()

def handle_shutdown(sig, loop, bot_manager):
    logging.info(f"Received shutdown signal {sig.name}. Stopping bots and saving state...")
    # Call bot manager to save state of all active bots
    if bot_manager:
        bot_manager.save_all_states()
    
    for task in running_tasks:
        task.cancel()

async def main():
    setup_logging()
    logging.info(f"Initializing TitanGrid Master Control in {config.MODE} mode...")

    # Shared queues for components that are "global"
    market_data_q = asyncio.Queue()
    
    # --- Instantiate Global/Shared Modules ---
    connector = ExchangeConnector(
        symbols=config.SYMBOLS, # This will later be managed by BotManager
        output_queue=market_data_q
    )
    
    # The data handler needs to be aware of all symbols being traded
    # A more advanced version might have one data handler per symbol
    data_handler = DataHandler(
        input_queue=market_data_q,
        # This queue is now effectively managed inside the bot manager
    )

    # --- Instantiate Lifecycle and Orchestration Managers ---
    bot_manager = BotManager(connector=connector, data_handler=data_handler)
    orchestrator = MasterOrchestrator(bot_manager=bot_manager)

    # --- Create and Track Core Service Tasks ---
    tasks_to_run = [
        orchestrator.run(),
        connector.run(),
        data_handler.run(),
    ]
    
    for coro in tasks_to_run:
        task = asyncio.create_task(coro)
        running_tasks.add(task)
        task.add_done_callback(running_tasks.discard)

    logging.info(f"Starting {len(running_tasks)} core service tasks...")
    
    try:
        await asyncio.gather(*running_tasks)
    except asyncio.CancelledError:
        logging.info("Main task group cancelled. Bot is shutting down.")

if __name__ == "__main__":
    # This block is now primarily for local script-based execution
    # For Docker deployment, the app.py/Gunicorn is the entry point.
    loop = asyncio.get_event_loop()
    
    # The bot_manager instance must be created here to be passed to the shutdown handler
    # This highlights the complexity of managing shared state in top-level scripts
    temp_connector = ExchangeConnector(symbols=[], output_queue=asyncio.Queue())
    temp_data_handler = DataHandler(input_queue=asyncio.Queue(), strategy_input_queue=asyncio.Queue())
    main_bot_manager = BotManager(connector=temp_connector, data_handler=temp_data_handler)
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_shutdown, sig, loop, main_bot_manager)

    try:
        loop.run_until_complete(main())
    finally:
        logging.info("Bot shutdown complete.")
        loop.close()
