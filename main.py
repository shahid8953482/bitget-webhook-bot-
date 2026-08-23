import logging
from typing import Optional, Union, Dict, Any
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
    version="1.1.0"
)

# ----------------------------------------------------
# Pydantic Schemas for Webhook Request Validation
# ----------------------------------------------------
class WebhookPayload(BaseModel):
    passphrase: Optional[str] = Field(default=None, description="Security passphrase matching WEBHOOK_PASSPHRASE")
    secret: Optional[str] = Field(default=None, description="Alternative field name for passphrase")
    
    action: str = Field(..., description="Action: buy, sell, long, short, close_long, close_short, close")
    symbol: Optional[str] = Field(default=None, description="Trading pair ticker e.g. BTCUSDT")
    ticker: Optional[str] = Field(default=None, description="Alternative field for symbol")
    
    # Amount / Contracts / Quantity flex fields
    amount: Optional[float] = Field(default=None, description="Order quantity/contracts")
    contracts: Optional[float] = Field(default=None, description="TradingView strategy contracts")
    quantity: Optional[float] = Field(default=None, description="Alternative name for amount")
    
    # Percentage sizing parameter (e.g. 10 for 10% of portfolio)
    percent: Optional[float] = Field(default=None, description="Percentage of account portfolio balance (e.g. 10 for 10%)")
    
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
    action = payload.action.lower()
    symbol = payload.get_symbol()
    amount = payload.get_amount()

    logger.info(f"Signal Details -> Action: {action.upper()} | Symbol: {symbol} | Amount: {amount} | Market: {payload.market_type}")

    # 3. Handle 'close' or 'close_all' position signals
    if action in ["close", "close_all"]:
        ccxt_symbol = bitget_client.normalize_symbol(symbol, payload.market_type)
        result = bitget_client.close_all_positions_for_symbol(ccxt_symbol)
        exec_status = "success" if result.get("success") else "error"
        database.log_webhook(
            action=action,
            symbol=symbol,
            amount=0.0,
            market_type=payload.market_type,
            status=exec_status,
            tv_payload=raw_payload,
            exchange_response=result
        )
        return {"message": "Position closed signal processed", "details": result}

    # Dynamic Percentage Portfolio Sizing if percent parameter is provided (e.g. 10%)
    if (amount <= 0) and payload.percent and payload.percent > 0:
        amount = bitget_client.calculate_amount_from_percent(
            symbol=symbol,
            percent=payload.percent,
            leverage=payload.leverage or 10,
            market_type=payload.market_type
        )
        logger.info(f"Dynamic {payload.percent}% Portfolio Sizing -> Calculated Amount: {amount} {symbol}")

    # Validation: Amount required for entry orders
    if amount <= 0:
        logger.error(f"Invalid order amount: {amount}. Must be > 0.")
        err_res = {"error": "Order amount or percent must be greater than 0"}
        database.log_webhook(
            action=action,
            symbol=symbol,
            amount=amount,
            market_type=payload.market_type,
            status="error",
            tv_payload=raw_payload,
            exchange_response=err_res
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Order amount/contracts or percent must be greater than 0"
        )

    # 4. Execute Order on Bitget
    result = bitget_client.execute_order(
        symbol=symbol,
        action=action,
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
        action=action,
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
