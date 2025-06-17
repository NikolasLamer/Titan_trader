# titan/exchange_connector.py
import asyncio
import json
import logging
import random
import time
from websockets.client import connect
from websockets.exceptions import ConnectionClosed

from titan.config import config
from titan.datastructures import Order

# Import the synchronous HTTP client from pybit
from pybit.unified_trading import HTTP

class ExchangeConnector:
    """
    Handles all network I/O with the exchange.
    - Manages WebSocket for market data.
    - Manages authenticated REST API calls for order execution via pybit.
    """
    def __init__(self, symbols: list, output_queue: asyncio.Queue):
        self.symbols = symbols
        self.ws_url = config.WEBSOCKET_URL
        self.output_queue = output_queue
        self.mode = config.MODE

        # --- PYBIT INTEGRATION ---
        # Initialize the synchronous pybit HTTP client for REST API calls
        if self.mode == 'LIVE':
            self.pybit_session = HTTP(
                testnet=False, 
                api_key=config.API_KEY, 
                api_secret=config.API_SECRET
            )
            logging.info("Initialized LIVE pybit HTTP session.")
        else:
            self.pybit_session = None
            logging.info("Running in SIMULATION mode. pybit session not created.")

    # ... (WebSocket methods _subscribe and _run_live/_run_simulation remain the same) ...
    async def _subscribe(self, websocket):
        subscription_args = [f"publicTrade.{symbol}" for symbol in self.symbols]
        msg = {"op": "subscribe", "args": subscription_args}
        await websocket.send(json.dumps(msg))
        logging.info(f"Subscribed to: {subscription_args}")

    async def _run_live(self):
        async for websocket in connect(self.ws_url, ping_interval=20):
            logging.info(f"Connected to LIVE feed at {self.ws_url}")
            await self._subscribe(websocket)
            try:
                async for message in websocket:
                    await self.output_queue.put(json.loads(message))
            except ConnectionClosed as e:
                logging.error(f"Live connection closed: {e}. Reconnecting...")
                await asyncio.sleep(5)
            except Exception:
                logging.critical("Unexpected live connector error", exc_info=True)
                await asyncio.sleep(15)
                
    async def _run_simulation(self):
        logging.info("Starting SIMULATED market data feed.")
        price = 30000.0
        while True:
            for symbol in self.symbols:
                price_change = random.uniform(-0.001, 0.001) * price
                price += price_change
                trade_data = {"topic": f"publicTrade.{symbol}", "type": "snapshot", "ts": int(time.time() * 1000), "data": [{"T": int(time.time() * 1000), "s": symbol, "S": "Buy" if price_change > 0 else "Sell", "v": f"{random.uniform(0.001, 1):.3f}", "p": f"{price:.2f}", "L": "PlusTick", "i": f"sim-trade-id-{random.randint(1000,9999)}", "BT": False}]}
                await self.output_queue.put(trade_data)
            await asyncio.sleep(0.5)

    async def run(self):
        if self.mode == 'LIVE':
            await self._run_live()
        else:
            await self._run_simulation()

    # --- Authenticated REST API Methods ---

    async def place_order(self, order: Order) -> dict:
        """
        Places an order on the exchange using pybit.
        This is a non-blocking wrapper around a synchronous library call.
        """
        if self.mode != 'LIVE':
            logging.info(f"[SIMULATION] Placing order: {order}")
            # In simulation, we assume the order is placed successfully
            return {"retCode": 0, "retMsg": "OK", "result": {"orderId": f"sim-{random.randint(1,1e6)}"}, "retExtInfo": {}}

        loop = asyncio.get_running_loop()
        try:
            logging.info(f"Placing LIVE order: {order}")
            # The pybit call is synchronous, so we run it in an executor
            response = await loop.run_in_executor(
                None,  # Use default thread pool executor
                lambda: self.pybit_session.place_order(
                    category="linear", # Or "spot" depending on config
                    symbol=order.symbol,
                    side=order.side,
                    orderType=order.order_type,
                    qty=str(order.qty),
                    price=str(order.price) if order.price else None
                )
            )
            
            if response and response.get('retCode') == 0:
                logging.info(f"Successfully placed order for {order.symbol}. Order ID: {response['result']['orderId']}")
            else:
                logging.error(f"Failed to place order for {order.symbol}: {response.get('retMsg')}")

            return response
        except Exception as e:
            logging.error(f"Exception during order placement for {order.symbol}: {e}", exc_info=True)
            return {"retCode": -1, "retMsg": str(e), "result": {}}

    async def get_account_balance(self) -> dict:
        """Fetches the account wallet balance."""
        if self.mode != 'LIVE':
            return {"retCode": 0, "result": {"list": [{"coin": [{"coin": "USDT", "equity": str(config.INITIAL_CAPITAL)}]}]}}
            
        loop = asyncio.get_running_loop()
        try:
            response = await loop.run_in_executor(
                None,
                lambda: self.pybit_session.get_wallet_balance(accountType="UNIFIED")
            )
            return response
        except Exception as e:
            logging.error(f"Exception fetching account balance: {e}", exc_info=True)
            return {"retCode": -1, "retMsg": str(e)}
