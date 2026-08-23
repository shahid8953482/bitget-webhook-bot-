import requests
import json
import time

BASE_URL = "http://127.0.0.1:8000"
WEBHOOK_URL = f"{BASE_URL}/webhook"
HEALTH_URL = f"{BASE_URL}/health"

# Passphrase configured in .env
PASSPHRASE = "my_super_secret_passphrase_123"

def print_header(title):
    print("\n" + "=" * 60)
    print(f" {title}")
    print("=" * 60)

def test_health():
    print_header("1. Testing Health Endpoint (/health)")
    try:
        res = requests.get(HEALTH_URL)
        print(f"Status Code: {res.status_code}")
        print("Response:", json.dumps(res.json(), indent=2))
    except Exception as e:
        print("Error connecting to server. Is main.py running?")
        print(f"Details: {e}")

def test_invalid_passphrase():
    print_header("2. Testing Invalid Passphrase (Security Check)")
    payload = {
        "passphrase": "wrong_passphrase_xxx",
        "action": "buy",
        "symbol": "BTCUSDT",
        "amount": 0.001
    }
    res = requests.post(WEBHOOK_URL, json=payload)
    print(f"Status Code: {res.status_code} (Expected: 401)")
    print("Response:", res.text)

def test_valid_long_webhook():
    print_header("3. Testing Valid LONG Strategy Signal")
    payload = {
        "passphrase": PASSPHRASE,
        "action": "long",
        "symbol": "BTCUSDT",
        "amount": 0.001,
        "market_type": "futures",
        "leverage": 10,
        "order_type": "market"
    }
    print("Sending Payload:")
    print(json.dumps(payload, indent=2))
    res = requests.post(WEBHOOK_URL, json=payload)
    print(f"Status Code: {res.status_code}")
    print("Response:", json.dumps(res.json(), indent=2))

def test_valid_close_webhook():
    print_header("4. Testing Valid CLOSE Position Signal")
    payload = {
        "passphrase": PASSPHRASE,
        "action": "close",
        "symbol": "BTCUSDT",
        "market_type": "futures"
    }
    print("Sending Payload:")
    print(json.dumps(payload, indent=2))
    res = requests.post(WEBHOOK_URL, json=payload)
    print(f"Status Code: {res.status_code}")
    print("Response:", json.dumps(res.json(), indent=2))

if __name__ == "__main__":
    print("\n[+] Starting Webhook Bot Local Tests...")
    test_health()
    time.sleep(1)
    test_invalid_passphrase()
    time.sleep(1)
    test_valid_long_webhook()
    time.sleep(1)
    test_valid_close_webhook()
    print("\n[+] Tests Complete!")
