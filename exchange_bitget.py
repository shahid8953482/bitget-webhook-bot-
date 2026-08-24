import logging
import ccxt
from typing import Dict, Any, Optional, List
from config import config

logger = logging.getLogger("bitget_bot")

class BitgetExchange:
    def __init__(self):
        self.api_key = config.BITGET_API_KEY
        self.secret = config.BITGET_SECRET
        self.passphrase = config.BITGET_PASSPHRASE
        self.use_testnet = config.USE_TESTNET

        self._spot_exchange = None
        self._futures_exchange = None
        self._initialize_exchanges()

    def _initialize_exchanges(self):
        """Initialize CCXT Bitget spot and futures exchange instances."""
        from dotenv import load_dotenv
        import os
        load_dotenv(override=True)
        
        self.api_key = os.getenv("BITGET_API_KEY", "")
        self.secret = os.getenv("BITGET_SECRET", "")
        self.passphrase = os.getenv("BITGET_PASSPHRASE", "")
        self.use_testnet = os.getenv("USE_TESTNET", "false").lower() in ("true", "1", "yes")

        common_config = {
            'apiKey': self.api_key,
            'secret': self.secret,
            'password': self.passphrase,
            'enableRateLimit': True,
            'options': {
                'adjustForTimeDifference': True,
                'createMarketBuyOrderRequiresPrice': False
            }
        }

        # Initialize Futures (Swap) instance
        try:
            futures_config = common_config.copy()
            futures_config['options'] = {'defaultType': 'swap'}
            self._futures_exchange = ccxt.bitget(futures_config)
            if self.use_testnet:
                self._futures_exchange.set_sandbox_mode(True)
            logger.info("Bitget Futures exchange initialized.")
        except Exception as e:
            logger.error(f"Failed to initialize Bitget Futures exchange: {e}")

        # Initialize Spot instance
        try:
            spot_config = common_config.copy()
            spot_config['options'] = {
                'defaultType': 'spot',
                'createMarketBuyOrderRequiresPrice': False
            }
            self._spot_exchange = ccxt.bitget(spot_config)
            if self.use_testnet:
                self._spot_exchange.set_sandbox_mode(True)
            logger.info("Bitget Spot exchange initialized.")
        except Exception as e:
            logger.error(f"Failed to initialize Bitget Spot exchange: {e}")

    def normalize_symbol(self, raw_symbol: str, market_type: str = "futures") -> str:
        """
        Normalize TradingView symbols (e.g. BTCUSDT, BTCUSDT.P, BTC/USDT) 
        to CCXT unified format (e.g. 'BTC/USDT:USDT' for futures, 'BTC/USDT' for spot).
        """
        cleaned = raw_symbol.upper().replace(".P", "").replace(".PERP", "").replace("/", "").replace("-", "")
        
        # Determine base & quote (Assuming USDT quote by default)
        if cleaned.endswith("USDT"):
            base = cleaned[:-4]
            quote = "USDT"
        elif cleaned.endswith("USD"):
            base = cleaned[:-3]
            quote = "USD"
        elif cleaned.endswith("USDC"):
            base = cleaned[:-4]
            quote = "USDC"
        else:
            # Fallback
            base = cleaned
            quote = "USDT"

        if market_type == "spot":
            return f"{base}/{quote}"
        else:
            # USDT-M Perpetual futures format in CCXT: BASE/QUOTE:MARGIN_CURRENCY
            return f"{base}/{quote}:{quote}"

    def set_leverage(self, symbol: str, leverage: int, margin_mode: str = "cross") -> bool:
        """Set leverage for a futures symbol."""
        try:
            if not self._futures_exchange:
                logger.error("Futures exchange not initialized.")
                return False

            params = {'marginMode': margin_mode.lower()}
            self._futures_exchange.set_leverage(leverage, symbol, params)
            logger.info(f"Successfully set leverage to {leverage}x on {symbol} ({margin_mode})")
            return True
        except Exception as e:
            logger.warning(f"Set leverage warning for {symbol}: {e}")
            return False

    def calculate_amount_from_percent(self, symbol: str, percent: float, leverage: int = 10, market_type: str = "futures") -> float:
        """Calculate coin contract amount based on percentage of available account balance."""
        self._initialize_exchanges()
        bal_res = self.get_account_balance(market_type)
        if not bal_res.get("success"):
            logger.error("Could not fetch account balance for percentage sizing")
            return 0.0
        
        available_usdt = float(bal_res.get("total_usdt", 0.0) or 0.0)
        if available_usdt <= 0:
            logger.error("Available balance is 0 for percentage sizing")
            return 0.0

        margin_to_use = available_usdt * (percent / 100.0)
        position_notional = margin_to_use * (leverage if market_type == "futures" else 1.0)
        
        # Fetch current coin price
        ccxt_symbol = self.normalize_symbol(symbol, market_type)
        exchange = self._futures_exchange if market_type == "futures" else self._spot_exchange
        if not exchange:
            return 0.0

        try:
            ticker = exchange.fetch_ticker(ccxt_symbol)
            price = float(ticker.get("last", 0.0) or ticker.get("close", 0.0) or 1.0)
            if price <= 0:
                return 0.0
            
            amount = position_notional / price
            # Round based on market precision (e.g. 0.0007 BTC)
            try:
                prec_str = exchange.amount_to_precision(ccxt_symbol, amount)
                return float(prec_str)
            except Exception:
                return round(amount, 4)
        except Exception as e:
            logger.error(f"Error fetching ticker for {ccxt_symbol}: {e}")
            return 0.0

    def execute_order(
        self,
        symbol: str,
        action: str,
        amount: float,
        market_type: str = "futures",
        order_type: str = "market",
        price: Optional[float] = None,
        leverage: Optional[int] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        reduce_only: bool = False
    ) -> Dict[str, Any]:
        """
        Execute an order on Bitget via CCXT.
        """
        self._initialize_exchanges()
        if not self.api_key or not self.secret or not self.passphrase:
            return {
                "success": False,
                "error": "API Keys not configured in .env file!",
                "symbol": symbol
            }

        exchange = self._futures_exchange if market_type == "futures" else self._spot_exchange
        if not exchange:
            return {"success": False, "error": f"{market_type.capitalize()} exchange not initialized"}

        ccxt_symbol = self.normalize_symbol(symbol, market_type)
        action_lower = action.lower()

        # Set leverage if specified for futures
        if market_type == "futures" and leverage and leverage > 0:
            self.set_leverage(ccxt_symbol, leverage)

        # Auto-close existing positions on Futures before opening new Strategy entry/reversal
        if market_type == "futures" and action_lower in ["buy", "long", "sell", "short"]:
            try:
                logger.info(f"Auto-closing existing positions for {ccxt_symbol} before new {action_lower.upper()} entry...")
                self.close_all_positions_for_symbol(ccxt_symbol)
            except Exception as e:
                logger.warning(f"Auto-close check warning for {ccxt_symbol}: {e}")

        params: Dict[str, Any] = {}

        # Determine side (buy vs sell), tradeSide, holdSide, and reduceOnly parameters
        if action_lower in ["buy", "long"]:
            side = "buy"
            if market_type == "futures":
                params["tradeSide"] = "open"
                params["holdSide"] = "long"
                params["posSide"] = "long"
        elif action_lower in ["sell", "short"]:
            side = "sell"
            if market_type == "futures":
                params["tradeSide"] = "open"
                params["holdSide"] = "short"
                params["posSide"] = "short"
        elif action_lower == "close_long":
            side = "sell"
            if market_type == "futures":
                params["tradeSide"] = "close"
                params["holdSide"] = "long"
                params["posSide"] = "long"
                params["reduceOnly"] = True
        elif action_lower == "close_short":
            side = "buy"
            if market_type == "futures":
                params["tradeSide"] = "close"
                params["holdSide"] = "short"
                params["posSide"] = "short"
                params["reduceOnly"] = True
        elif action_lower == "close":
            # Will handle via custom close helper
            return self.close_all_positions_for_symbol(ccxt_symbol)
        else:
            return {"success": False, "error": f"Invalid action: {action}"}

        if reduce_only:
            params["reduceOnly"] = True

        # Attach SL / TP params if provided
        if stop_loss and stop_loss > 0:
            params["stopLossPrice"] = stop_loss
        if take_profit and take_profit > 0:
            params["takeProfitPrice"] = take_profit

        try:
            logger.info(f"Placing {order_type.upper()} {side.upper()} order on {ccxt_symbol} | Amount: {amount} | Params: {params}")
            
            if market_type == "spot" and side == "buy":
                params["createMarketBuyOrderRequiresPrice"] = False
                params["createOrder"] = {"createMarketBuyOrderRequiresPrice": False}
                order = exchange.create_order(
                    symbol=ccxt_symbol,
                    type="market",
                    side=side,
                    amount=amount,
                    params=params
                )
            else:
                order = exchange.create_order(
                    symbol=ccxt_symbol,
                    type="market" if order_type.lower() != "limit" else "limit",
                    side=side,
                    amount=amount,
                    price=price,
                    params=params
                )

            logger.info(f"Order executed successfully! Order ID: {order.get('id')}")
            return {
                "success": True,
                "order_id": order.get("id"),
                "symbol": ccxt_symbol,
                "side": side,
                "amount": amount,
                "price": order.get("price") or price,
                "status": order.get("status"),
                "raw_response": order
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error placing order on Bitget for {ccxt_symbol}: {error_msg}")
            
            # Code 40774 fallback: User switched Bitget Futures account to One-Way Mode (Unilateral Position Mode)
            if "40774" in error_msg or "unilateral" in error_msg.lower():
                logger.info(f"Account is in One-Way Mode. Retrying order execution without Hedge parameters for {ccxt_symbol}...")
                try:
                    oneway_params = {"reduceOnly": True} if (reduce_only or "close" in action_lower) else {}
                    order = exchange.create_order(
                        symbol=ccxt_symbol,
                        type="market" if order_type.lower() != "limit" else "limit",
                        side=side,
                        amount=amount,
                        price=price,
                        params=oneway_params
                    )
                    logger.info(f"One-Way Mode Order executed successfully! Order ID: {order.get('id')}")
                    return {
                        "success": True,
                        "order_id": order.get("id"),
                        "symbol": ccxt_symbol,
                        "side": side,
                        "amount": amount,
                        "price": order.get("price") or price,
                        "status": order.get("status"),
                        "raw_response": order
                    }
                except Exception as ex2:
                    error_msg = str(ex2)
                    logger.error(f"One-Way Mode Retry error for {ccxt_symbol}: {error_msg}")

            return {
                "success": False,
                "error": error_msg,
                "symbol": ccxt_symbol,
                "action": action
            }

    def close_all_positions_for_symbol(self, ccxt_symbol: str) -> Dict[str, Any]:
        """Fetch open positions for a symbol and close them using market reduceOnly orders with holdSide."""
        try:
            if not self._futures_exchange:
                return {"success": False, "error": "Futures exchange not initialized"}

            positions = self._futures_exchange.fetch_positions([ccxt_symbol])
            closed_results = []

            for pos in positions:
                contracts = float(pos.get("contracts", 0) or pos.get("size", 0) or pos.get("total", 0) or 0)
                if contracts > 0:
                    pos_side = str(pos.get("side", "") or pos.get("holdSide", "") or "long").lower()
                    if pos_side == "short":
                        close_side = "buy"
                        hold_side = "short"
                    else:
                        close_side = "sell"
                        hold_side = "long"
                    
                    close_params = {
                        "reduceOnly": True,
                        "tradeSide": "close",
                        "holdSide": hold_side,
                        "posSide": hold_side
                    }
                    
                    try:
                        order = self._futures_exchange.create_order(
                            symbol=ccxt_symbol,
                            type="market",
                            side=close_side,
                            amount=contracts,
                            params=close_params
                        )
                    except Exception as close_err:
                        if "40774" in str(close_err) or "unilateral" in str(close_err).lower():
                            order = self._futures_exchange.create_order(
                                symbol=ccxt_symbol,
                                type="market",
                                side=close_side,
                                amount=contracts,
                                params={"reduceOnly": True}
                            )
                        else:
                            raise close_err

                    closed_results.append({
                        "side": pos_side,
                        "closed_amount": contracts,
                        "order_id": order.get("id")
                    })

            if not closed_results:
                return {"success": True, "message": f"No open positions found for {ccxt_symbol}"}

            return {
                "success": True,
                "symbol": ccxt_symbol,
                "closed_positions": closed_results
            }

        except Exception as e:
            logger.error(f"Error closing position for {ccxt_symbol}: {e}")
            return {"success": False, "error": str(e), "symbol": ccxt_symbol}

    def get_account_balance(self, market_type: str = "futures") -> Dict[str, Any]:
        """Fetch account balance for spot, futures, or all."""
        self._initialize_exchanges()
        
        if market_type == "all":
            futures_res = self.get_account_balance("futures")
            spot_res = self.get_account_balance("spot")
            
            f_total = futures_res.get("total_usdt", 0.0) if futures_res.get("success") else 0.0
            s_total = spot_res.get("total_usdt", 0.0) if spot_res.get("success") else 0.0
            
            return {
                "success": True,
                "market_type": "all",
                "total_usdt": round(f_total + s_total, 2),
                "futures_usdt": f_total,
                "spot_usdt": s_total
            }

        try:
            exchange = self._futures_exchange if market_type == "futures" else self._spot_exchange
            if not exchange:
                return {"success": False, "error": "Exchange not initialized"}
            
            balance = exchange.fetch_balance()
            total_usdt = balance.get("total", {}).get("USDT", 0.0)
            free_usdt = balance.get("free", {}).get("USDT", 0.0)

            return {
                "success": True,
                "market_type": market_type,
                "total_usdt": round(total_usdt, 2),
                "usdt_cash": float(total_usdt),
                "raw": balance
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_open_positions(self) -> List[Dict[str, Any]]:
        """Fetch active live open positions from Bitget Futures V2 API."""
        self._initialize_exchanges()
        if not self._futures_exchange:
            return []
        
        try:
            res = self._futures_exchange.privateMixGetV2MixPositionAllPosition({'productType': 'USDT-FUTURES'})
            positions = []
            for pos in res.get("data", []):
                total_contracts = float(pos.get("total", 0) or pos.get("available", 0) or 0)
                if total_contracts > 0:
                    raw_symbol = pos.get("symbol", "")
                    clean_symbol = raw_symbol.replace("_UMCBL", "").replace("_SPBL", "")
                    hold_side = pos.get("holdSide", "long").lower()
                    positions.append({
                        "symbol": clean_symbol,
                        "side": hold_side,
                        "size": total_contracts,
                        "entry_price": float(pos.get("openPrice", 0) or pos.get("averageOpenPrice", 0) or 0),
                        "mark_price": float(pos.get("marketPrice", 0) or 0),
                        "margin": float(pos.get("margin", 0) or 0),
                        "leverage": pos.get("leverage", "10")
                    })
            return positions
        except Exception as e:
            logger.error(f"Error fetching open positions: {e}")
            return []

# Singleton instance
bitget_client = BitgetExchange()
