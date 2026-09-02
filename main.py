import logging
from typing import Optional, Union, Dict, Any, List
from fastapi import FastAPI, HTTPException, Request, Depends, status
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel, Field
import os

from config import config
from exchange_bitget import bitget_client
import database

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("bitget_bot")

app = FastAPI(
    title="Bitget TradingView Webhook Bot",
    description="Automated Trading Bot receiving TradingView alerts and executing on Bitget",
    version="1.3.0"
)

# ----------------------------------------------------
# Pydantic Schemas for Webhook Request Validation
# ----------------------------------------------------
class WebhookPayload(BaseModel):
    passphrase: Optional[str] = Field(default=None, description="Security passphrase matching WEBHOOK_PASSPHRASE")
    secret: Optional[str] = Field(default=None, description="Alternative field name for passphrase")
    
    action: str = Field(..., description="Action: buy, sell, long, short, exitbuy, exitsell, close_long, close_short, close")
    symbol: Optional[str] = Field(default=None, description="Trading pair ticker e.g. BTCUSDT")
    ticker: Optional[str] = Field(default=None, description="Alternative field for symbol")
    
    # Amount / Contracts / Quantity flex fields
    amount: Optional[float] = Field(default=None, description="Order quantity/contracts")
    contracts: Optional[float] = Field(default=None, description="TradingView strategy contracts")
    quantity: Optional[float] = Field(default=None, description="Alternative name for amount")
    
    market_type: str = Field(default="futures", description="'futures' (swap) or 'spot'")
    order_type: str = Field(default="market", description="'market' or 'limit'")
    price: Optional[float] = Field(default=None, description="Price for limit orders")
    leverage: Optional[int] = Field(default=None, description="Leverage value (e.g. 10)")
    
    stop_loss: Optional[float] = Field(default=None, description="Stop loss price")
    take_profit: Optional[float] = Field(default=None, description="Take profit price")

    def get_passphrase(self) -> str:
        return self.passphrase or self.secret or ""

    def get_symbol(self) -> str:
        return self.symbol or self.ticker or "BTCUSDT"

    def get_amount(self) -> float:
        val = self.amount or self.contracts or self.quantity or 0.0
        return abs(float(val))

# ----------------------------------------------------
# Dashboard & REST API Endpoints
# ----------------------------------------------------

@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
def serve_dashboard():
    """Serve the Web Dashboard HTML page."""
    html_path = os.path.join(os.path.dirname(__file__), "templates", "dashboard.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    return HTMLResponse("<h2>Dashboard template not found</h2>", status_code=404)

@app.get("/health")
def health_check():
    api_configured = config.validate_keys()
    return {
        "status": "healthy",
        "api_keys_configured": api_configured,
        "testnet": config.USE_TESTNET,
        "port": config.PORT
    }

@app.get("/balance")
def get_balance(market: str = "futures"):
    return bitget_client.get_account_balance(market_type=market)

@app.get("/api/positions")
def get_positions(symbol: Optional[str] = None):
    """Retrieve active open positions from Bitget."""
    return bitget_client.get_open_positions(symbol=symbol)

@app.get("/api/logs")
def get_webhook_logs(limit: int = 100):
    return database.get_logs(limit=limit)

@app.get("/api/stats")
def get_stats():
    return database.get_stats()

@app.delete("/api/logs")
def clear_all_logs():
    success = database.clear_logs()
    return {"success": success, "message": "Logs cleared"}

@app.post("/webhook")
async def receive_webhook(payload: WebhookPayload, request: Request):
    """
    Main Webhook listener receiving JSON alert payload from TradingView.
    """
    client_ip = request.client.host if request.client else "unknown"
    logger.info(f"Incoming Webhook received from IP: {client_ip}")
    raw_payload = payload.model_dump()

    # 1. Verify Passphrase Security
    request_passphrase = payload.get_passphrase()
    if request_passphrase != config.WEBHOOK_PASSPHRASE:
        logger.warning(f"Unauthorized Webhook attempt! Invalid passphrase: '{request_passphrase}' from {client_ip}")
        err_res = {"error": "Invalid security passphrase", "status": "unauthorized"}
        database.log_webhook(
            action=payload.action,
            symbol=payload.get_symbol(),
            amount=payload.get_amount(),
            market_type=payload.market_type,
            status="unauthorized",
            tv_payload=raw_payload,
            exchange_response=err_res
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid security passphrase"
        )

    # 2. Extract and sanitize values
    raw_action = payload.action.strip()
    action_clean = raw_action.lower().replace(" ", "").replace("_", "").replace("-", "")
    symbol = payload.get_symbol()
    amount = payload.get_amount()

    logger.info(f"Signal Details -> Action: {raw_action.upper()} (Clean: {action_clean}) | Symbol: {symbol} | Amount: {amount} | Market: {payload.market_type}")

    # Map of all known close/exit signal variants
    EXIT_ACTIONS_MAP = {
        # Long exit variants
        "exitbuy": "long",
        "exitlong": "long",
        "closebuy": "long",
        "closelong": "long",
        "close_long": "long",
        "close_buy": "long",
        "closelongposition": "long",
        "exitbuyorder": "long",
        
        # Short exit variants
        "exitsell": "short",
        "exitshort": "short",
        "closesell": "short",
        "closeshort": "short",
        "close_short": "short",
        "close_sell": "short",
        "closeshortposition": "short",
        "exitsellorder": "short",

        # General close / flat variants
        "close": None,
        "closeall": None,
        "close_all": None,
        "closepositions": None,
        "exit": None,
        "exitall": None,
        "flatten": None
    }

    is_exit_action = (
        action_clean in EXIT_ACTIONS_MAP or
        action_clean.startswith("exit") or
        action_clean.startswith("close")
    )

    # 3. Handle Exit / Close Signals
    if is_exit_action:
        target_side = EXIT_ACTIONS_MAP.get(action_clean)
        if target_side is None:
            if "buy" in action_clean or "long" in action_clean:
                target_side = "long"
            elif "sell" in action_clean or "short" in action_clean:
                target_side = "short"

        logger.info(f"Handling Exit Signal: Target Side={target_side or 'ALL'} | Symbol={symbol} | Amount={amount or '100% full position'}")
        
        result = bitget_client.close_position(
            symbol=symbol,
            target_side=target_side,
            amount=amount if amount > 0 else None,
            market_type=payload.market_type
        )

        exec_status = "success" if result.get("success") else "error"
        database.log_webhook(
            action=raw_action,
            symbol=symbol,
            amount=amount if amount > 0 else 0.0,
            market_type=payload.market_type,
            status=exec_status,
            tv_payload=raw_payload,
            exchange_response=result
        )

        if result.get("success"):
            return {
                "status": "success",
                "message": f"Exit/Close signal processed for {symbol}",
                "details": result
            }
        else:
            return {
                "status": "error",
                "message": f"Failed to execute exit/close on Bitget",
                "error": result.get("error")
            }

    # 4. For Entry Orders (BUY, SELL, LONG, SHORT):
    # If amount is not specified in TradingView alert, auto-calculate optimal safe size!
    if amount <= 0:
        amount = bitget_client.calculate_default_amount(
            symbol=symbol,
            price=payload.price,
            market_type=payload.market_type
        )
        logger.info(f"Amount omitted in webhook alert. Auto-calculated order size: {amount} {symbol}")

    # 5. Execute Entry Order on Bitget
    result = bitget_client.execute_order(
        symbol=symbol,
        action=raw_action,
        amount=amount,
        market_type=payload.market_type,
        order_type=payload.order_type,
        price=payload.price,
        leverage=payload.leverage,
        stop_loss=payload.stop_loss,
        take_profit=payload.take_profit
    )

    exec_status = "success" if result.get("success") else "error"
    database.log_webhook(
        action=raw_action,
        symbol=symbol,
        amount=amount,
        market_type=payload.market_type,
        status=exec_status,
        tv_payload=raw_payload,
        exchange_response=result
    )

    if result.get("success"):
        logger.info(f"Trade successfully placed! Order ID: {result.get('order_id')}")
        return {
            "status": "success",
            "message": "Order executed successfully on Bitget",
            "order": result
        }
    else:
        logger.error(f"Trade execution failed: {result.get('error')}")
        return {
            "status": "error",
            "message": "Failed to execute order on Bitget",
            "error": result.get("error")
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=True)
