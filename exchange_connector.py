# titan/exchange_connector.py
import asyncio
import json
import logging
import random
import time
from websockets.client import connect
from websockets.exceptions import ConnectionClosed

from titan.config import config

class ExchangeConnector:
    """
    Handles all network I/O with the exchange.
    Operates in two modes: SIMULATION or LIVE.
    """
    def __init__(self, symbols: list, output_queue: asyncio.Queue):
        self.symbols = symbols
        self.ws_url = config.WEBSOCKET_URL
        self.output_queue = output_queue
        self.mode = config.MODE

    async def _subscribe(self, websocket):
        """Sends subscription messages for the specified symbols."""
        subscription_args = [f"publicTrade.{symbol}" for symbol in self.symbols]
        msg = {"op": "subscribe", "args": subscription_args}
        await websocket.send(json.dumps(msg))
        logging.info(f"Subscribed to: {subscription_args}")

    async def _run_live(self):
        """Main run loop for live mode."""
        async for websocket in connect(self.ws_url, ping_interval=20):
            logging.info(f"Connected to LIVE feed at {self.ws_url}")
            await self._subscribe(websocket)
            try:
                async for message in websocket:
                    await self.output_queue.put(json.loads(message))
            except ConnectionClosed as e:
                logging.error(f"Live connection closed: {e}. Reconnecting...")
                await asyncio.sleep(5)
            except Exception as e:
                logging.critical("Unexpected live connector error", exc_info=True)
                await asyncio.sleep(15)
                
    async def _run_simulation(self):
        """Generates a simulated market data feed."""
        logging.info("Starting SIMULATED market data feed.")
        price = 30000.0
        while True:
            for symbol in self.symbols:
                price_change = random.uniform(-0.001, 0.001) * price
                price += price_change
                trade_data = {
                    "topic": f"publicTrade.{symbol}",
                    "type": "snapshot",
                    "ts": int(time.time() * 1000),
                    "data": [{
                        "T": int(time.time() * 1000),
                        "s": symbol,
                        "S": "Buy" if price_change > 0 else "Sell",
                        "v": f"{random.uniform(0.001, 1):.3f}",
                        "p": f"{price:.2f}",
                        "L": "PlusTick",
                        "i": f"simulated-trade-id-{random.randint(1000,9999)}",
                        "BT": False
                    }]
                }
                await self.output_queue.put(trade_data)
            await asyncio.sleep(0.5) # New trade every 500ms

    async def run(self):
        """Entry point to run the connector in the configured mode."""
        if self.mode == 'LIVE':
            await self._run_live()
        else:
            await self._run_simulation()

    # --- Placeholder REST methods for OrderExecutor ---
    async def place_order(self, order: dict):
        logging.info(f"PLACING ORDER (via REST): {order}")
        # In LIVE mode, this would use aiohttp/SDK to send a signed request
        # and return the exchange's response.
        if self.mode == 'LIVE':
             # await self.rest_client.post('/v5/order/create', data=order)
             pass
        # In SIMULATION, we can just log it. Fills will be handled by the simulator.
        return {"status": "ok", "orderId": f"sim-{random.randint(1,1e6)}"}
