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

import asyncio
import requests

app = FastAPI(
    title="Bitget TradingView Webhook Bot",
    description="Automated Trading Bot receiving TradingView alerts and executing on Bitget",
    version="1.1.0"
)

async def keep_alive_ping_loop():
    """Background task to self-ping server every 4 minutes to prevent Render free instance from sleeping."""
    await asyncio.sleep(10)
    while True:
        try:
            render_url = "https://bitget-webhook-bot-8qsl.onrender.com/health"
            requests.get(render_url, timeout=5)
            logger.info("24/7 Keep-Alive ping sent to Render cloud server.")
        except Exception:
            pass
        await asyncio.sleep(240)  # Ping every 4 minutes (240 seconds)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(keep_alive_ping_loop())

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

DEFAULT_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bitget TradingView Webhook Dashboard</title>
    <!-- Google Fonts: Inter -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <!-- Font Awesome Icons -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
    
    <style>
        :root {
            --bg-main: #0b0f19;
            --bg-card: #131c2e;
            --bg-card-hover: #1a263e;
            --border-color: #23314d;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --accent-green: #10b981;
            --accent-red: #ef4444;
            --accent-blue: #3b82f6;
            --accent-purple: #8b5cf6;
            --accent-yellow: #f59e0b;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: 'Inter', sans-serif;
        }

        body {
            background-color: var(--bg-main);
            color: var(--text-primary);
            min-height: 100vh;
            padding: 24px;
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
        }

        /* Header */
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 24px;
            border-bottom: 1px solid var(--border-color);
            margin-bottom: 24px;
            flex-wrap: wrap;
            gap: 16px;
        }

        .logo-group {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .logo-icon {
            width: 44px;
            height: 44px;
            background: linear-gradient(135deg, var(--accent-blue), var(--accent-purple));
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 20px;
            color: #fff;
            box-shadow: 0 4px 15px rgba(59, 130, 246, 0.3);
        }

        .logo-title h1 {
            font-size: 20px;
            font-weight: 700;
            letter-spacing: -0.5px;
        }

        .logo-title p {
            font-size: 12px;
            color: var(--text-secondary);
        }

        .header-actions {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .status-badge {
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: rgba(16, 185, 129, 0.1);
            color: var(--accent-green);
            border: 1px solid rgba(16, 185, 129, 0.3);
        }

        .pulse-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background-color: var(--accent-green);
            box-shadow: 0 0 8px var(--accent-green);
            animation: pulse 2s infinite;
        }

        @keyframes pulse {
            0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
            70% { transform: scale(1); box-shadow: 0 0 0 10px rgba(16, 185, 129, 0); }
            100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
        }

        .btn {
            background-color: var(--bg-card);
            color: var(--text-primary);
            border: 1px solid var(--border-color);
            padding: 8px 16px;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 500;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            transition: all 0.2s ease;
        }

        .btn:hover {
            background-color: var(--bg-card-hover);
            border-color: var(--accent-blue);
        }

        .btn-danger:hover {
            border-color: var(--accent-red);
            color: var(--accent-red);
        }

        /* Stats Grid */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }

        .stat-card {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 14px;
            padding: 20px;
            transition: transform 0.2s ease, border-color 0.2s ease;
        }

        .stat-card:hover {
            transform: translateY(-2px);
            border-color: rgba(59, 130, 246, 0.4);
        }

        .stat-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
            color: var(--text-secondary);
            font-size: 13px;
            font-weight: 500;
        }

        .stat-icon {
            width: 36px;
            height: 36px;
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 16px;
        }

        .stat-val {
            font-size: 26px;
            font-weight: 700;
            letter-spacing: -0.5px;
        }

        .stat-desc {
            font-size: 12px;
            color: var(--text-secondary);
            margin-top: 4px;
        }

        /* Signal Log Table Section */
        .section-card {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 14px;
            overflow: hidden;
        }

        .section-header {
            padding: 18px 24px;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 12px;
        }

        .section-title {
            font-size: 16px;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .table-responsive {
            overflow-x: auto;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            text-align: left;
            font-size: 13px;
        }

        th {
            background: rgba(15, 23, 42, 0.6);
            color: var(--text-secondary);
            font-weight: 600;
            padding: 14px 20px;
            border-bottom: 1px solid var(--border-color);
            white-space: nowrap;
        }

        td {
            padding: 14px 20px;
            border-bottom: 1px solid rgba(35, 49, 77, 0.5);
            vertical-align: middle;
            white-space: nowrap;
        }

        tr:hover td {
            background-color: var(--bg-card-hover);
        }

        /* Badges */
        .badge {
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            display: inline-block;
        }

        .badge-buy, .badge-long { background: rgba(16, 185, 129, 0.15); color: var(--accent-green); border: 1px solid rgba(16, 185, 129, 0.3); }
        .badge-sell, .badge-short { background: rgba(239, 68, 68, 0.15); color: var(--accent-red); border: 1px solid rgba(239, 68, 68, 0.3); }
        .badge-close { background: rgba(59, 130, 246, 0.15); color: var(--accent-blue); border: 1px solid rgba(59, 130, 246, 0.3); }
        .badge-success { background: rgba(16, 185, 129, 0.1); color: var(--accent-green); }
        .badge-error { background: rgba(239, 68, 68, 0.1); color: var(--accent-red); }
        .badge-unauthorized { background: rgba(245, 158, 11, 0.1); color: var(--accent-yellow); }

        .empty-state {
            padding: 60px 20px;
            text-align: center;
            color: var(--text-secondary);
        }

        .empty-state i {
            font-size: 40px;
            margin-bottom: 12px;
            opacity: 0.5;
        }

        /* Modal */
        .modal-overlay {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.7);
            backdrop-filter: blur(4px);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 1000;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.2s ease;
        }

        .modal-overlay.active {
            opacity: 1;
            pointer-events: auto;
        }

        .modal {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            width: 90%;
            max-width: 900px;
            max-height: 85vh;
            display: flex;
            flex-direction: column;
            box-shadow: 0 20px 40px rgba(0,0,0,0.5);
        }

        .modal-header {
            padding: 20px 24px;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .modal-title {
            font-size: 16px;
            font-weight: 600;
        }

        .modal-close {
            background: none;
            border: none;
            color: var(--text-secondary);
            font-size: 20px;
            cursor: pointer;
        }

        .modal-body {
            padding: 24px;
            overflow-y: auto;
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
        }

        @media (max-width: 768px) {
            .modal-body { grid-template-columns: 1fr; }
        }

        .json-block {
            background: #080c14;
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 14px;
        }

        .json-block h4 {
            font-size: 12px;
            color: var(--text-secondary);
            margin-bottom: 8px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        pre {
            font-family: monospace;
            font-size: 12px;
            color: #38bdf8;
            white-space: pre-wrap;
            word-break: break-all;
        }
    </style>
</head>
<body>

<div class="container">
    <!-- Header -->
    <header>
        <div class="logo-group">
            <div class="logo-icon"><i class="fa-solid fa-bolt"></i></div>
            <div class="logo-title">
                <h1>Bitget Webhook Dashboard</h1>
                <p>TradingView Signal Execution & Monitoring System</p>
            </div>
        </div>
        <div class="header-actions">
            <div class="status-badge" id="status-badge">
                <span class="pulse-dot"></span>
                <span id="status-text">BOT ONLINE</span>
            </div>
            <button class="btn" onclick="fetchData()">
                <i class="fa-solid fa-rotate"></i> Refresh
            </button>
            <button class="btn btn-danger" onclick="clearLogs()">
                <i class="fa-solid fa-trash-can"></i> Clear Logs
            </button>
        </div>
    </header>

    <!-- Stats Cards -->
    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-header">
                <span>TOTAL SIGNALS</span>
                <div class="stat-icon" style="background: rgba(59, 130, 246, 0.1); color: var(--accent-blue);">
                    <i class="fa-solid fa-signal"></i>
                </div>
            </div>
            <div class="stat-val" id="stat-total">0</div>
            <div class="stat-desc">Total TradingView alerts received</div>
        </div>

        <div class="stat-card">
            <div class="stat-header">
                <span>SUCCESSFUL EXECUTIONS</span>
                <div class="stat-icon" style="background: rgba(16, 185, 129, 0.1); color: var(--accent-green);">
                    <i class="fa-solid fa-circle-check"></i>
                </div>
            </div>
            <div class="stat-val" style="color: var(--accent-green);" id="stat-success">0</div>
            <div class="stat-desc" id="stat-rate">Success Rate: 100%</div>
        </div>

        <div class="stat-card">
            <div class="stat-header">
                <span>FAILED / ERRORS</span>
                <div class="stat-icon" style="background: rgba(239, 68, 68, 0.1); color: var(--accent-red);">
                    <i class="fa-solid fa-triangle-exclamation"></i>
                </div>
            </div>
            <div class="stat-val" style="color: var(--accent-red);" id="stat-errors">0</div>
            <div class="stat-desc">Execution errors or API key issues</div>
        </div>

        <div class="stat-card">
            <div class="stat-card-inner">
                <div class="stat-header">
                    <span>BITGET BALANCE (USDT)</span>
                    <div class="stat-icon" style="background: rgba(139, 92, 246, 0.1); color: var(--accent-purple);">
                        <i class="fa-solid fa-wallet"></i>
                    </div>
                </div>
                <div class="stat-val" style="color: var(--accent-purple);" id="stat-balance">$0.00</div>
                <div class="stat-desc" id="stat-mode">Mode: Testnet / Live</div>
            </div>
        </div>
    </div>

    <!-- Active Open Positions Section -->
    <div class="section-card" style="margin-bottom: 24px;">
        <div class="section-header">
            <div class="section-title">
                <i class="fa-solid fa-chart-line" style="color: var(--accent-purple);"></i>
                Active Open Positions (Bitget Futures)
            </div>
            <div style="font-size: 12px; color: var(--text-secondary);" id="positions-count-badge">
                0 Active Positions
            </div>
        </div>

        <div class="table-responsive">
            <table>
                <thead>
                    <tr>
                        <th>Symbol</th>
                        <th>Side</th>
                        <th>Size (Contracts)</th>
                        <th>Entry Price</th>
                        <th>Mark Price</th>
                        <th>Margin (USDT)</th>
                        <th>Leverage</th>
                    </tr>
                </thead>
                <tbody id="positions-tbody">
                    <tr>
                        <td colspan="7">
                            <div class="empty-state" style="padding: 24px 20px;">
                                <i class="fa-solid fa-folder-open"></i>
                                <p>No active open positions on Bitget Futures right now.</p>
                            </div>
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>

    <!-- Webhook Logs Table -->
    <div class="section-card">
        <div class="section-header">
            <div class="section-title">
                <i class="fa-solid fa-list-check" style="color: var(--accent-blue);"></i>
                Webhook Execution Logs
            </div>
            <div style="font-size: 12px; color: var(--text-secondary);">
                Auto-refreshing every 5 seconds
            </div>
        </div>

        <div class="table-responsive">
            <table>
                <thead>
                    <tr>
                        <th>Time</th>
                        <th>Action</th>
                        <th>Symbol</th>
                        <th>Amount / Contracts</th>
                        <th>Market</th>
                        <th>Status</th>
                        <th>Details</th>
                    </tr>
                </thead>
                <tbody id="logs-tbody">
                    <tr>
                        <td colspan="7">
                            <div class="empty-state">
                                <i class="fa-solid fa-spinner fa-spin"></i>
                                <p>Loading webhook signals...</p>
                            </div>
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>
</div>

<!-- JSON Payload Inspector Modal -->
<div class="modal-overlay" id="modal-overlay">
    <div class="modal">
        <div class="modal-header">
            <div class="modal-title" id="modal-title">Signal Payload Details</div>
            <button class="modal-close" onclick="closeModal()">&times;</button>
        </div>
        <div class="modal-body">
            <div class="json-block">
                <h4><i class="fa-solid fa-arrow-down-left-and-arrow-up-right"></i> TradingView Received Payload</h4>
                <pre id="modal-tv-json">{}</pre>
            </div>
            <div class="json-block">
                <h4><i class="fa-solid fa-paper-plane"></i> Bitget Exchange Response</h4>
                <pre id="modal-bitget-json">{}</pre>
            </div>
        </div>
    </div>
</div>

<script>
    let logsCache = [];

    async function fetchData() {
        try {
            // 1. Fetch Stats
            const statsRes = await fetch('/api/stats');
            const stats = await statsRes.json();
            
            document.getElementById('stat-total').innerText = stats.total_signals || 0;
            document.getElementById('stat-success').innerText = stats.success_count || 0;
            document.getElementById('stat-errors').innerText = stats.error_count || 0;
            document.getElementById('stat-rate').innerText = `Success Rate: ${stats.success_rate}%`;

            // 2. Fetch Balance & Mode
            const healthRes = await fetch('/health');
            const health = await healthRes.json();
            document.getElementById('stat-mode').innerText = health.testnet ? "Mode: Testnet (Demo)" : "Mode: Real Live Trading";

            const balRes = await fetch('/balance?market=all');
            const bal = await balRes.json();
            if (bal.success) {
                document.getElementById('stat-balance').innerText = `$${parseFloat(bal.total_usdt || 0).toFixed(2)}`;
            } else {
                document.getElementById('stat-balance').innerText = "Keys Required";
            }

            // 3. Fetch Open Positions
            try {
                const posRes = await fetch('/api/positions');
                const positions = await posRes.json();
                renderPositions(positions);
            } catch(e) {
                console.error("Positions fetch error:", e);
            }

            // 4. Fetch Logs
            const logsRes = await fetch('/api/logs');
            const logs = await logsRes.json();
            logsCache = logs;
            renderLogs(logs);

        } catch (err) {
            console.error("Failed to fetch dashboard data:", err);
        }
    }

    function renderPositions(positions) {
        const tbody = document.getElementById('positions-tbody');
        const badge = document.getElementById('positions-count-badge');
        
        if (!positions || positions.length === 0) {
            badge.innerText = "0 Active Positions";
            tbody.innerHTML = `
                <tr>
                    <td colspan="7">
                        <div class="empty-state" style="padding: 20px;">
                            <i class="fa-solid fa-folder-open"></i>
                            <p style="font-size: 13px;">No active open positions on Bitget Futures right now.</p>
                        </div>
                    </td>
                </tr>
            `;
            return;
        }

        badge.innerText = `${positions.length} Active Position(s)`;
        tbody.innerHTML = positions.map(pos => {
            const isLong = pos.side.toLowerCase() === 'long';
            const sideClass = isLong ? 'badge-long' : 'badge-short';
            return `
                <tr>
                    <td style="font-weight: 700; color: var(--text-primary);">${pos.symbol}</td>
                    <td><span class="badge ${sideClass}">${pos.side.toUpperCase()}</span></td>
                    <td style="font-weight: 600;">${pos.size}</td>
                    <td>$${parseFloat(pos.entry_price || 0).toFixed(2)}</td>
                    <td>$${parseFloat(pos.mark_price || 0).toFixed(2)}</td>
                    <td style="color: var(--accent-purple); font-weight: 600;">$${parseFloat(pos.margin || 0).toFixed(2)}</td>
                    <td><span class="badge" style="background: rgba(139, 92, 246, 0.15); color: var(--accent-purple);">${pos.leverage}x</span></td>
                </tr>
            `;
        }).join('');
    }

    function renderLogs(logs) {
        const tbody = document.getElementById('logs-tbody');
        if (!logs || logs.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="7">
                        <div class="empty-state">
                            <i class="fa-solid fa-inbox"></i>
                            <p>No webhook signals received yet.<br><small>Send an alert from TradingView or run test_webhook.py to see live signals here.</small></p>
                        </div>
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = logs.map((log, index) => {
            let actionClass = 'badge-close';
            const actionUpper = log.action.toUpperCase();
            if (actionUpper.includes('BUY') || actionUpper.includes('LONG')) actionClass = 'badge-long';
            if (actionUpper.includes('SELL') || actionUpper.includes('SHORT')) actionClass = 'badge-short';

            let statusClass = 'badge-success';
            if (log.status === 'error') statusClass = 'badge-error';
            if (log.status === 'unauthorized') statusClass = 'badge-unauthorized';

            return `
                <tr>
                    <td style="color: var(--text-secondary); font-size: 12px;">${log.timestamp}</td>
                    <td><span class="badge ${actionClass}">${log.action}</span></td>
                    <td style="font-weight: 600;">${log.symbol}</td>
                    <td>${log.amount ? log.amount : '-'}</td>
                    <td style="text-transform: capitalize;">${log.market_type || 'futures'}</td>
                    <td><span class="badge ${statusClass}">${log.status}</span></td>
                    <td>
                        <button class="btn" style="padding: 4px 10px; font-size: 11px;" onclick="inspectLog(${index})">
                            <i class="fa-solid fa-code"></i> Inspect JSON
                        </button>
                    </td>
                </tr>
            `;
        }).join('');
    }

    function inspectLog(index) {
        const log = logsCache[index];
        if (!log) return;

        document.getElementById('modal-title').innerText = `Signal #${log.id} - ${log.action} ${log.symbol} (${log.timestamp})`;
        document.getElementById('modal-tv-json').innerText = JSON.stringify(log.tradingview_payload, null, 2);
        document.getElementById('modal-bitget-json').innerText = JSON.stringify(log.exchange_response, null, 2);
        
        document.getElementById('modal-overlay').classList.add('active');
    }

    function closeModal() {
        document.getElementById('modal-overlay').classList.remove('active');
    }

    async function clearLogs() {
        if (confirm("Are you sure you want to clear all webhook logs?")) {
            await fetch('/api/logs', { method: 'DELETE' });
            fetchData();
        }
    }

    // Initial Load & Auto Refresh
    fetchData();
    setInterval(fetchData, 5000);
</script>

</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
def serve_dashboard():
    """Serve the Web Dashboard HTML page with robust path resolution."""
    possible_paths = [
        os.path.join(os.path.dirname(__file__), "templates", "dashboard.html"),
        os.path.join(os.getcwd(), "templates", "dashboard.html"),
        os.path.join(os.path.dirname(__file__), "dashboard.html"),
        os.path.join(os.getcwd(), "dashboard.html"),
    ]
    for path in possible_paths:
        if os.path.exists(path):
            return FileResponse(path)
    return HTMLResponse(content=DEFAULT_DASHBOARD_HTML)

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
def get_open_positions():
    """Return active live open positions on Bitget Futures."""
    return bitget_client.get_open_positions()

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

    # 3. Check for close/exit signals (e.g. 'close', 'Close entry(s) order target01_buy', etc.)
    is_close_signal = any(term in action for term in ["close", "exit", "cancel", "target01"])
    
    if is_close_signal:
        ccxt_symbol = bitget_client.normalize_symbol(symbol, payload.market_type)
        open_positions = bitget_client.get_open_positions()
        matching_pos = [p for p in open_positions if bitget_client.normalize_symbol(p["symbol"], "futures") == ccxt_symbol]
        
        if not matching_pos:
            logger.info(f"No active open position found for {symbol}. Ignoring close signal cleanly without placing any order on Bitget.")
            ign_res = {"success": True, "message": f"No open position found for {symbol}. Close signal ignored cleanly."}
            database.log_webhook(
                action=action,
                symbol=symbol,
                amount=0.0,
                market_type=payload.market_type,
                status="success",
                tv_payload=raw_payload,
                exchange_response=ign_res
            )
            return {"status": "success", "message": f"No active position for {symbol}. Close signal ignored cleanly.", "details": ign_res}
            
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
        return {"status": "success", "message": "Position closed signal processed", "details": result}

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
