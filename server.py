"""
Binance CopyTrade Position Monitor - Cookie Session
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import time
import threading
import os
from datetime import datetime

app = Flask(__name__)
CORS(app)

CONFIG = {
    "telegram_token":  os.environ.get("TELEGRAM_TOKEN", ""),
    "telegram_chat_id":os.environ.get("TELEGRAM_CHAT_ID", ""),
    "poll_interval":   int(os.environ.get("POLL_INTERVAL", "30")),
    "cookie":          os.environ.get("BINANCE_COOKIE", ""),
    "csrftoken":       os.environ.get("BINANCE_CSRF", ""),
}

previous_positions = {}
monitor_active = False
monitor_thread = None

def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{CONFIG['telegram_token']}/sendMessage"
        payload = {"chat_id": CONFIG["telegram_chat_id"], "text": message, "parse_mode": "HTML"}
        r = requests.post(url, json=payload, timeout=10)
        return r.json()
    except Exception as e:
        print(f"[Telegram Error] {e}")
        return None

def get_copy_positions():
    """Ambil posisi CopyTrade yang sedang berlangsung"""
    try:
        url = "https://www.binance.com/bapi/futures/v1/private/future/copy-trade/copy-portfolio/detail-list?ongoing=true"
        headers = {
            "accept": "*/*",
            "accept-language": "id",
            "bnc-location": "ID",
            "bnc-time-zone": "Asia/Jakarta",
            "bnc-uuid": "8eea9e11-4fd7-41de-b6f4-0d7840d5a1bb",
            "clienttype": "web",
            "content-type": "application/json",
            "csrftoken": CONFIG["csrftoken"],
            "cookie": CONFIG["cookie"],
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
        }
        r = requests.get(url, headers=headers, timeout=15)
        data = r.json()

        if data.get("code") == "000000" and data.get("data"):
            portfolios = data["data"]
            # Ambil posisi dari setiap portfolio yang ongoing
            all_positions = {}
            for portfolio in portfolios:
                portfolio_id = portfolio.get("copyPortfolioId")
                if portfolio_id:
                    positions = get_portfolio_positions(portfolio_id)
                    for p in positions:
                        symbol = p.get("symbol", "")
                        if symbol:
                            all_positions[symbol] = p
            return all_positions
        else:
            print(f"[CopyTrade] Response: {data}")
            return {}
    except Exception as e:
        print(f"[Error get_copy_positions] {e}")
        return {}

def get_portfolio_positions(portfolio_id):
    """Ambil detail posisi dari satu portfolio"""
    try:
        url = f"https://www.binance.com/bapi/futures/v1/private/future/copy-trade/copy-portfolio/position-list?copyPortfolioId={portfolio_id}"
        headers = {
            "accept": "*/*",
            "accept-language": "id",
            "bnc-location": "ID",
            "bnc-time-zone": "Asia/Jakarta",
            "bnc-uuid": "8eea9e11-4fd7-41de-b6f4-0d7840d5a1bb",
            "clienttype": "web",
            "content-type": "application/json",
            "csrftoken": CONFIG["csrftoken"],
            "cookie": CONFIG["cookie"],
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
        }
        r = requests.get(url, headers=headers, timeout=15)
        data = r.json()
        if data.get("code") == "000000" and data.get("data"):
            return data["data"] if isinstance(data["data"], list) else []
        return []
    except Exception as e:
        print(f"[Error get_portfolio_positions] {e}")
        return []

def format_open(pos):
    amount = float(pos.get("amount", pos.get("positionAmt", 0)))
    side = "LONG 📈" if amount > 0 else "SHORT 📉"
    symbol = pos.get("symbol", "?")
    entry = float(pos.get("entryPrice", 0))
    amt = abs(amount)
    pnl = float(pos.get("pnl", pos.get("unrealizedProfit", 0)))
    leverage = pos.get("leverage", "?")
    ts = datetime.now().strftime("%H:%M:%S")
    return (
        f"🟢 <b>OPEN {side}</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📌 <b>{symbol}</b>\n"
        f"💰 Entry: <b>${entry:,.4f}</b>\n"
        f"📦 Size: <b>{amt}</b>\n"
        f"⚡ Leverage: <b>{leverage}x</b>\n"
        f"📊 PnL: <b>${pnl:+.2f}</b>\n"
        f"🕐 {ts}"
    )

def format_close(prev):
    amount = float(prev.get("amount", prev.get("positionAmt", 0)))
    side = "LONG" if amount > 0 else "SHORT"
    symbol = prev.get("symbol", "?")
    entry = float(prev.get("entryPrice", 0))
    pnl = float(prev.get("pnl", prev.get("unrealizedProfit", 0)))
    emoji = "✅" if pnl >= 0 else "❌"
    ts = datetime.now().strftime("%H:%M:%S")
    return (
        f"🔴 <b>CLOSE {side}</b> {emoji}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📌 <b>{symbol}</b>\n"
        f"💰 Entry was: <b>${entry:,.4f}</b>\n"
        f"📊 PnL: <b>${pnl:+.2f}</b>\n"
        f"🕐 {ts}"
    )

def format_size_change(pos, prev):
    old_amt = abs(float(prev.get("amount", prev.get("positionAmt", 0))))
    new_amt = abs(float(pos.get("amount", pos.get("positionAmt", 0))))
    diff = new_amt - old_amt
    direction = "➕ Tambah size" if diff > 0 else "➖ Kurang size"
    symbol = pos.get("symbol", "?")
    ts = datetime.now().strftime("%H:%M:%S")
    return (
        f"🔄 <b>{direction}</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📌 <b>{symbol}</b>\n"
        f"📦 {old_amt} → <b>{new_amt}</b> ({diff:+.4f})\n"
        f"🕐 {ts}"
    )

def check_positions():
    global previous_positions
    current = get_copy_positions()
    changes = []

    for symbol, pos in current.items():
        if symbol not in previous_positions:
            msg = format_open(pos)
            send_telegram(msg)
            changes.append({"type": "open", "symbol": symbol})
            print(f"[OPEN] {symbol}")
        else:
            prev = previous_positions[symbol]
            old_amt = abs(float(prev.get("amount", prev.get("positionAmt", 0))))
            new_amt = abs(float(pos.get("amount", pos.get("positionAmt", 0))))
            if abs(old_amt - new_amt) > 0.0001:
                msg = format_size_change(pos, prev)
                send_telegram(msg)
                changes.append({"type": "size_change", "symbol": symbol})
                print(f"[SIZE CHANGE] {symbol}")

    for symbol, prev in previous_positions.items():
        if symbol not in current:
            msg = format_close(prev)
            send_telegram(msg)
            changes.append({"type": "close", "symbol": symbol})
            print(f"[CLOSE] {symbol}")

    previous_positions = current
    return current, changes

def monitor_loop():
    global monitor_active
    print(f"[Monitor] Mulai polling setiap {CONFIG['poll_interval']} detik...")
    send_telegram("🤖 <b>Bot Monitor aktif!</b>\nMemantau posisi CopyTrade kamu...")
    while monitor_active:
        check_positions()
        time.sleep(CONFIG['poll_interval'])
    send_telegram("⏹ <b>Bot Monitor dihentikan.</b>")

@app.route('/')
def home():
    return jsonify({"status": "CopyTrade Monitor running!"})

@app.route('/api/status')
def status():
    return jsonify({
        "active": monitor_active,
        "positions": list(previous_positions.values()),
        "position_count": len(previous_positions)
    })

@app.route('/api/positions')
def get_positions():
    try:
        active, _ = check_positions()
        return jsonify({
            "success": True,
            "positions": list(active.values()),
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/monitor/start', methods=['POST'])
def start_monitor():
    global monitor_active, monitor_thread
    if monitor_active:
        return jsonify({"success": False, "message": "Monitor sudah aktif"})
    monitor_active = True
    monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
    monitor_thread.start()
    return jsonify({"success": True, "message": "Monitor dimulai"})

@app.route('/api/monitor/stop', methods=['POST'])
def stop_monitor():
    global monitor_active
    monitor_active = False
    return jsonify({"success": True, "message": "Monitor dihentikan"})

@app.route('/api/test/telegram', methods=['POST'])
def test_telegram():
    result = send_telegram("✅ <b>Test berhasil!</b>\nBot monitor terhubung ke Telegram.")
    if result and result.get('ok'):
        return jsonify({"success": True, "message": "Pesan test terkirim!"})
    return jsonify({"success": False, "message": str(result)})

@app.route('/api/debug')
def debug():
    try:
        import hmac, hashlib, time
        api_key = os.environ.get("BINANCE_API_KEY", "")
        secret = os.environ.get("BINANCE_SECRET", "")
        timestamp = int(time.time() * 1000)
        params = f"timestamp={timestamp}"
        signature = hmac.new(
            secret.encode('utf-8'),
            params.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        url = f"https://api.binance.com/sapi/v1/copyTrading/futures/currentCopyTrade?{params}&signature={signature}"
        headers = {"X-MBX-APIKEY": api_key}
        r = requests.get(url, headers=headers, timeout=10)
        return jsonify({"status": r.status_code, "raw": r.json()})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/api/myip')
def myip():
    import urllib.request
    ip = urllib.request.urlopen('https://api.ipify.org').read().decode()
    return jsonify({"ip": ip})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("=" * 50)
    print("  Binance CopyTrade Monitor")
    print(f"  http://0.0.0.0:{port}")
    print("=" * 50)
    app.run(host='0.0.0.0', port=port, debug=False)
