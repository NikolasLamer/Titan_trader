# app.py
import asyncio
import logging
from flask import Flask, jsonify, request

# Import the bot's main coroutine and setup function
from main import main as run_bot_main
from titan.logger import setup_logging

# Configure logging
setup_logging()

# --- Flask App Initialization ---
app = Flask(__name__)

# Global variable to hold the asyncio task for the bot
bot_task = None

@app.before_request
async def startup():
    """
    On the first request, start the bot as a background asyncio task.
    This ensures the bot starts automatically when the container runs.
    """
    global bot_task
    if bot_task is None:
        logging.info("Flask server started. Launching bot as a background task...")
        loop = asyncio.get_running_loop()
        bot_task = loop.create_task(run_bot_main())

@app.route('/status', methods=['GET'])
def status():
    """Endpoint to check the status of the bot task."""
    global bot_task
    if bot_task and not bot_task.done():
        return jsonify({"status": "running"}), 200
    elif bot_task and bot_task.done():
        try:
            # If the task finished, check if it raised an exception
            exception = bot_task.exception()
            if exception:
                logging.error(f"Bot task finished with an exception: {exception}")
                return jsonify({"status": "crashed", "error": str(exception)}), 500
            else:
                return jsonify({"status": "stopped"}), 200
        except asyncio.CancelledError:
            return jsonify({"status": "stopped"}), 200
    else:
        return jsonify({"status": "not_started"}), 200

@app.route('/start', methods=['POST'])
async def start_bot():
    """Endpoint to manually start the bot if it was stopped."""
    global bot_task
    if bot_task is None or bot_task.done():
        logging.info("Received /start command. Launching bot...")
        loop = asyncio.get_running_loop()
        bot_task = loop.create_task(run_bot_main())
        return jsonify({"status": "started"}), 201
    else:
        return jsonify({"status": "already_running"}), 409

@app.route('/stop', methods=['POST'])
async def stop_bot():
    """Endpoint to gracefully stop the bot."""
    global bot_task
    if bot_task and not bot_task.done():
        logging.info("Received /stop command. Stopping bot...")
        bot_task.cancel()
        try:
            await bot_task # Wait for the task to acknowledge cancellation
        except asyncio.CancelledError:
            logging.info("Bot task successfully cancelled.")
        bot_task = None
        return jsonify({"status": "stopping"}), 200
    else:
        return jsonify({"status": "not_running"}), 404
