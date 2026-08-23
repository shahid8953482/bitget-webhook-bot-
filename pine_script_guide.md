# TradingView Alert JSON Payloads for Bitget Bot

Copy & Paste these JSON message templates into your TradingView Alert settings!

> **IMPORTANT**: Replace `my_super_secret_passphrase_123` with the passphrase you set in your `.env` file!

---

## 1. Strategy Alert Payload (Automated Long & Short)

When creating an alert for a **Pine Script Strategy** (using `strategy.entry()` / `strategy.close()`), set **Condition** to `Your Strategy Name` -> `Order fills only`.

### Message Body (Copy & Paste into Alert Message Box):
```json
{
  "passphrase": "my_super_secret_passphrase_123",
  "action": "{{strategy.order.action}}",
  "symbol": "{{ticker}}",
  "contracts": {{strategy.order.contracts}},
  "price": {{strategy.order.price}},
  "market_type": "futures",
  "leverage": 10,
  "order_type": "market"
}
```

---

## 2. Separate Manual Alerts for Indicators / Custom Alerts

If you are using a **Pine Script Indicator** (`alertcondition()` or `alert()`), create separate alerts for Long, Short, and Close:

### A. LONG Alert Payload
```json
{
  "passphrase": "my_super_secret_passphrase_123",
  "action": "long",
  "symbol": "{{ticker}}",
  "amount": 0.001,
  "market_type": "futures",
  "leverage": 10
}
```

### B. SHORT Alert Payload
```json
{
  "passphrase": "my_super_secret_passphrase_123",
  "action": "short",
  "symbol": "{{ticker}}",
  "amount": 0.001,
  "market_type": "futures",
  "leverage": 10
}
```

### C. CLOSE Position Alert Payload
```json
{
  "passphrase": "my_super_secret_passphrase_123",
  "action": "close",
  "symbol": "{{ticker}}",
  "market_type": "futures"
}
```

---

## 3. Spot Market Order Payload

For **Spot Trading** on Bitget:

```json
{
  "passphrase": "my_super_secret_passphrase_123",
  "action": "buy",
  "symbol": "BTCUSDT",
  "amount": 0.001,
  "market_type": "spot"
}
```

---

## 4. Webhook URL Configuration in TradingView

In your TradingView Alert Creation Window:
1. Go to the **Notifications** tab.
2. Check the **Webhook URL** checkbox.
3. Enter your bot's Webhook URL:
   - For Local Testing (via Ngrok): `https://your-ngrok-subdomain.ngrok-free.app/webhook`
   - For Cloud VPS / Render: `https://your-bot-name.onrender.com/webhook`
