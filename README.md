# 🤖 Bitget TradingView Webhook Trading Bot

FastAPI aur CCXT par mabni **Bitget Webhook Trading Bot** jo TradingView ki strategies/indicators ke alerts ko **Bitget Exchange** par automatically execute karta hai.

---

## 🌟 Main Features

- ⚡ **Spot & Futures (USDT-M)**: Market & Limit orders dono support karta hai.
- 🔒 **Secure Authentication**: Secret Passphrase validation taaki sirf aapke TradingView alerts execute hon.
- 📈 **Dynamic Position Sizing & Leverage**: Alert payload ke zariye leverage (e.g. 10x, 20x) aur contract size control karein.
- 🌐 **24/7 Cloud Support**: Docker & Render.com 1-click cloud deployment files shamil hain taaki PC off hone par bhi bot chalay.

---

## 🛠️ Step 1: Dependencies Install Karein

Apne terminal/cmd mein command chalayein:

```bash
pip install -r requirements.txt
```

---

## 🔑 Step 2: Bitget API Keys aur Settings Configure Karein

1. Bitget account par ja kar **API Management** se nayi API Key generate karein:
   - **Permissions**: Spot Trading, Futures Trading (Read/Write)
   - **Passphrase**: Apni marzi ka secret passphrase rakhein.
2. Is folder mein `.env` file kholein aur apni details enter karein:

```env
BITGET_API_KEY=your_actual_bitget_api_key
BITGET_SECRET=your_actual_bitget_secret
BITGET_PASSPHRASE=your_bitget_passphrase

# Set to true for Demo Trading (Testnet), false for Real Trading
USE_TESTNET=false

# Security Passphrase for TradingView Alert
WEBHOOK_PASSPHRASE=my_super_secret_passphrase_123
```

---

## 🚀 Step 3: Local Server Run Karein

Bot server start karne ke liye:

```bash
python main.py
```

Server `http://127.0.0.1:8000` par start ho jayega.

---

## 🧪 Step 4: Local Test Script Chalayein

Alag terminal window mein test script chalayein:

```bash
python test_webhook.py
```

Yeh script check karega ke bot online hai aur test payloads accept kar raha hai.

---

## 🌐 Step 5: PC Par Local Testing via Ngrok

TradingView se alerts recieve karne ke liye aapke local server ko public URL chahiye:

1. Free `ngrok` download karein: [https://ngrok.com](https://ngrok.com)
2. Command chalayein:
   ```bash
   ngrok http 8000
   ```
3. Ngrok aapko ek Forwarding URL dega (e.g. `https://xxxx.ngrok-free.app`).
4. Aapka TradingView Webhook URL yeh hoga:
   `https://xxxx.ngrok-free.app/webhook`

---

## ☁️ Step 6: 24/7 Bina PC Ke Chalane Ka Tarika (Free Cloud Hosting)

Agar aap apna PC off karna chahte hain aur chahte hain ke bot 24 ghante chalay:

### Option A: Render.com (Free Cloud Hosting)
1. GitHub par yeh project repository Push karein.
2. [Render.com](https://render.com) par free account banayein.
3. **New Web Service** par click karein aur apna GitHub repo connect karein.
4. Render aapki `render.yaml` ko automatically detect kar ke deploy kar dega.
5. Environment variables (BITGET_API_KEY, BITGET_SECRET, etc.) Render dashboard mein set karein.
6. Webhook URL: `https://your-bot-name.onrender.com/webhook`

---

## 📊 Step 7: TradingView Mein Alert Set Karein

TradingView par alert create karte waqt:
1. **Webhook URL** enable karein aur apna Webhook URL dalein: `https://your-bot-name.onrender.com/webhook`
2. **Message** box mein [pine_script_guide.md](file:///c:/Users/SHAHID%20ECU/Desktop/shahid%20ai/tredingvew%20strategy/pine_script_guide.md) se JSON format copy-paste karein:

```json
{
  "passphrase": "my_super_secret_passphrase_123",
  "action": "{{strategy.order.action}}",
  "symbol": "{{ticker}}",
  "contracts": {{strategy.order.contracts}},
  "price": {{strategy.order.price}},
  "market_type": "futures",
  "leverage": 10
}
```

---

## 📁 File Structure

- [main.py](file:///c:/Users/SHAHID%20ECU/Desktop/shahid%20ai/tredingvew%20strategy/main.py) - FastAPI Webhook server & endpoints.
- [exchange_bitget.py](file:///c:/Users/SHAHID%20ECU/Desktop/shahid%20ai/tredingvew%20strategy/exchange_bitget.py) - CCXT Bitget spot & futures integration.
- [config.py](file:///c:/Users/SHAHID%20ECU/Desktop/shahid%20ai/tredingvew%20strategy/config.py) - Settings loader.
- [pine_script_guide.md](file:///c:/Users/SHAHID%20ECU/Desktop/shahid%20ai/tredingvew%20strategy/pine_script_guide.md) - TradingView JSON alert templates.
- [test_webhook.py](file:///c:/Users/SHAHID%20ECU/Desktop/shahid%20ai/tredingvew%20strategy/test_webhook.py) - Local testing script.
- [Dockerfile](file:///c:/Users/SHAHID%20ECU/Desktop/shahid%20ai/tredingvew%20strategy/Dockerfile) & [render.yaml](file:///c:/Users/SHAHID%20ECU/Desktop/shahid%20ai/tredingvew%20strategy/render.yaml) - 24/7 Cloud deployment config.
