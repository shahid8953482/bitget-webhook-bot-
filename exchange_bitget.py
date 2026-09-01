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
        cleaned = raw_symbol.upper().replace(".P", "").replace(".PERP", "").replace("/", "").replace("-", "").replace(":USDT", "")
        
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
            base = cleaned
            quote = "USDT"

        if market_type == "spot":
            return f"{base}/{quote}"
        else:
            # USDT-M Perpetual futures format in CCXT: BASE/QUOTE:MARGIN_CURRENCY
            return f"{base}/{quote}:{quote}"

    def clean_ticker(self, symbol: str) -> str:
        """Extract clean symbol ticker e.g. ZECUSDT from ZEC/USDT:USDT or ZECUSDT.P"""
        return symbol.upper().replace(".P", "").replace(".PERP", "").replace("/", "").replace("-", "").replace(":USDT", "").replace(":USD", "")

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

    def get_open_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch all active open futures positions from Bitget."""
        self._initialize_exchanges()
        if not self._futures_exchange:
            return []

        try:
            positions = self._futures_exchange.fetch_positions()
            active_positions = []
            target_clean = self.clean_ticker(symbol) if symbol else None

            for p in positions:
                contracts = float(p.get("contracts", 0) or p.get("size", 0) or 0)
                if contracts > 0:
                    pos_sym = p.get("symbol", "")
                    clean_pos_sym = self.clean_ticker(pos_sym)
                    
                    if target_clean and clean_pos_sym != target_clean:
                        continue

                    side = str(p.get("side", "")).lower()
                    active_positions.append({
                        "symbol": pos_sym,
                        "clean_symbol": clean_pos_sym,
                        "side": side, # 'long' or 'short'
                        "contracts": contracts,
                        "entry_price": float(p.get("entryPrice") or 0),
                        "mark_price": float(p.get("markPrice") or 0),
                        "unrealized_pnl": float(p.get("unrealizedPnl") or 0),
                        "percentage": float(p.get("percentage") or 0),
                        "leverage": p.get("leverage") or 10,
                        "margin": float(p.get("initialMargin") or p.get("collateral") or 0),
                        "raw": p
                    })
            return active_positions
        except Exception as e:
            logger.error(f"Error fetching open positions from Bitget: {e}")
            return []

    def _create_futures_order(
        self,
        symbol: str,
        order_type: str,
        side: str,
        amount: float,
        price: Optional[float] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Safely place futures orders on Bitget.
        Handles One-Way Mode (empty params) and Two-Way/Hedge Mode (tradeSide) automatically.
        """
        if params is None:
            params = {}

        # 1. First Attempt with provided params
        try:
            if order_type.lower() == "limit" and price:
                return self._futures_exchange.create_order(
                    symbol=symbol,
                    type="limit",
                    side=side,
                    amount=amount,
                    price=price,
                    params=params
                )
            else:
                return self._futures_exchange.create_order(
                    symbol=symbol,
                    type="market",
                    side=side,
                    amount=amount,
                    params=params
                )
        except Exception as e:
            err_str = str(e)
            logger.warning(f"Futures order attempt failed: {err_str}. Checking for position mode conflict...")

            # Case A: Error 40773 ("Closed positions can only occur in two-way positions")
            # In One-Way mode on Bitget, BOTH reduceOnly and tradeSide cause 40773.
            # Fix: Retry as a pure market order with completely empty params!
            if "40773" in err_str or "two-way positions" in err_str or "Closed positions can only occur in two-way" in err_str:
                logger.info("Detected One-Way Mode on Bitget. Retrying as pure market order with empty params...")
                if order_type.lower() == "limit" and price:
                    return self._futures_exchange.create_order(
                        symbol=symbol,
                        type="limit",
                        side=side,
                        amount=amount,
                        price=price,
                        params={}
                    )
                else:
                    return self._futures_exchange.create_order(
                        symbol=symbol,
                        type="market",
                        side=side,
                        amount=amount,
                        params={}
                    )

            # Case B: Two-Way / Hedge Mode is active on account and requires tradeSide
            elif "tradeSide" in err_str or "posSide" in err_str or "two-way" in err_str:
                logger.info("Detected Two-Way (Hedge) Mode on Bitget. Retrying with tradeSide...")
                retry_params = params.copy()
                if "tradeSide" not in retry_params:
                    retry_params["tradeSide"] = "close"

                if order_type.lower() == "limit" and price:
                    return self._futures_exchange.create_order(
                        symbol=symbol,
                        type="limit",
                        side=side,
                        amount=amount,
                        price=price,
                        params=retry_params
                    )
                else:
                    return self._futures_exchange.create_order(
                        symbol=symbol,
                        type="market",
                        side=side,
                        amount=amount,
                        params=retry_params
                    )

            # Re-raise if other error
            raise e

    def close_position(
        self,
        symbol: str,
        target_side: Optional[str] = None, # 'long', 'short', or None for both
        amount: Optional[float] = None,
        market_type: str = "futures"
    ) -> Dict[str, Any]:
        """
        Closes active position for a symbol and optional side ('long' or 'short').
        Works seamlessly in One-Way Mode (Standard Market Order) and Hedge Mode on Bitget.
        If amount is None or <= 0, closes 100% of the active position.
        """
        self._initialize_exchanges()
        ccxt_symbol = self.normalize_symbol(symbol, market_type)

        if market_type == "spot":
            try:
                if not self._spot_exchange:
                    return {"success": False, "error": "Spot exchange not initialized"}
                
                base = symbol.upper().replace(".P", "").replace(".PERP", "").replace("/", "").replace("-", "").replace("USDT", "")
                balance = self._spot_exchange.fetch_balance()
                free_balance = float(balance.get("free", {}).get(base, 0) or 0)
                
                sell_amount = amount if (amount and amount > 0 and amount <= free_balance) else free_balance
                if sell_amount <= 0:
                    return {"success": True, "message": f"No {base} spot balance found to sell/exit"}

                order = self._spot_exchange.create_order(
                    symbol=f"{base}/USDT",
                    type="market",
                    side="sell",
                    amount=sell_amount
                )
                logger.info(f"Spot Exit executed: Sold {sell_amount} {base}. Order ID: {order.get('id')}")
                return {
                    "success": True,
                    "symbol": f"{base}/USDT",
                    "market_type": "spot",
                    "closed_amount": sell_amount,
                    "order_id": order.get("id")
                }
            except Exception as e:
                logger.error(f"Error executing Spot close for {symbol}: {e}")
                return {"success": False, "error": str(e), "symbol": symbol}

        # Futures close logic
        try:
            if not self._futures_exchange:
                return {"success": False, "error": "Futures exchange not initialized"}

            # Fetch open positions matching symbol
            positions = self.get_open_positions(symbol)
            if not positions:
                # Try finding across all active positions in case symbol formatting differed
                target_clean = self.clean_ticker(symbol)
                all_positions = self.get_open_positions()
                positions = [p for p in all_positions if p["clean_symbol"] == target_clean or target_clean in p["clean_symbol"]]

            closed_results = []
            for pos in positions:
                pos_side = pos["side"].lower() # 'long' or 'short'
                
                if target_side and pos_side != target_side.lower():
                    logger.info(f"Skipping {pos_side} position because target exit side is {target_side}")
                    continue

                contracts = pos["contracts"]
                close_amount = amount if (amount and amount > 0 and amount <= contracts) else contracts
                close_side = "sell" if pos_side == "long" else "buy"
                pos_sym = pos["symbol"] or ccxt_symbol

                logger.info(f"Sending Market Close Order: Symbol={pos_sym} | Side={close_side} | Amount={close_amount} | Closing Position={pos_side.upper()}")

                # In One-Way Mode (Single position mode), Bitget executes a pure market order (empty params).
                # _create_futures_order will auto-retry if Hedge Mode is active.
                order = self._create_futures_order(
                    symbol=pos_sym,
                    order_type="market",
                    side=close_side,
                    amount=close_amount,
                    params={}
                )

                closed_results.append({
                    "symbol": pos_sym,
                    "position_side": pos_side,
                    "order_side": close_side,
                    "closed_amount": close_amount,
                    "order_id": order.get("id"),
                    "status": order.get("status")
                })
                logger.info(f"Position successfully closed! Order ID: {order.get('id')}")

            if not closed_results:
                msg = f"No active {target_side.upper() if target_side else 'open'} position found for {symbol} on Bitget."
                logger.warning(msg)
                return {
                    "success": True,
                    "message": msg,
                    "symbol": ccxt_symbol,
                    "closed_positions": []
                }

            return {
                "success": True,
                "symbol": ccxt_symbol,
                "closed_positions": closed_results
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error closing futures position for {symbol}: {error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "symbol": ccxt_symbol
            }

    def close_all_positions_for_symbol(self, ccxt_symbol: str) -> Dict[str, Any]:
        """Backward compatible helper to close all positions for a symbol."""
        return self.close_position(symbol=ccxt_symbol, target_side=None, amount=None, market_type="futures")

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
        Execute an entry or exit order on Bitget via CCXT.
        """
        self._initialize_exchanges()
        if not self.api_key or not self.secret or not self.passphrase:
            return {
                "success": False,
                "error": "API Keys not configured in .env file!",
                "symbol": symbol
            }

        action_clean = action.lower().replace(" ", "").replace("_", "").replace("-", "")

        # Handle exit actions
        if action_clean in ["exitbuy", "exitlong", "closebuy", "closelong", "close_long"]:
            return self.close_position(symbol=symbol, target_side="long", amount=amount if amount > 0 else None, market_type=market_type)
        if action_clean in ["exitsell", "exitshort", "closesell", "closeshort", "close_short"]:
            return self.close_position(symbol=symbol, target_side="short", amount=amount if amount > 0 else None, market_type=market_type)
        if action_clean in ["close", "closeall", "exit", "exitall", "flatten"]:
            return self.close_position(symbol=symbol, target_side=None, amount=amount if amount > 0 else None, market_type=market_type)

        exchange = self._futures_exchange if market_type == "futures" else self._spot_exchange
        if not exchange:
            return {"success": False, "error": f"{market_type.capitalize()} exchange not initialized"}

        ccxt_symbol = self.normalize_symbol(symbol, market_type)

        # Set leverage if specified for futures
        if market_type == "futures" and leverage and leverage > 0:
            self.set_leverage(ccxt_symbol, leverage)

        params: Dict[str, Any] = {}

        # Determine side (buy vs sell)
        if action_clean in ["buy", "long"]:
            side = "buy"
        elif action_clean in ["sell", "short"]:
            side = "sell"
        else:
            return {"success": False, "error": f"Invalid action: {action}"}

        # Attach SL / TP params if provided
        if stop_loss and stop_loss > 0:
            params["stopLossPrice"] = stop_loss
        if take_profit and take_profit > 0:
            params["takeProfitPrice"] = take_profit

        try:
            logger.info(f"Placing {order_type.upper()} {side.upper()} order on {ccxt_symbol} | Amount: {amount} | Params: {params}")
            
            if market_type == "spot":
                if order_type.lower() == "limit" and price:
                    order = exchange.create_order(
                        symbol=ccxt_symbol,
                        type="limit",
                        side=side,
                        amount=amount,
                        price=price,
                        params=params
                    )
                else:
                    order = exchange.create_order(
                        symbol=ccxt_symbol,
                        type="market",
                        side=side,
                        amount=amount,
                        params=params
                    )
            else:
                # Use robust futures order handler for One-Way & Hedge mode compatibility
                order = self._create_futures_order(
                    symbol=ccxt_symbol,
                    order_type=order_type,
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
            return {
                "success": False,
                "error": error_msg,
                "symbol": ccxt_symbol,
                "action": action
            }

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
                "total_usdt": float(total_usdt),
                "free_usdt": float(free_usdt),
                "raw": balance
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

# Singleton instance
bitget_client = BitgetExchange()
