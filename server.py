"""
Binance CopyTrade Position Monitor - Leaderboard Scraper
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

# =============================================
# KONFIGURASI
# =============================================
CONFIG = {
    "portfolio_id":    os.environ.get("PORTFOLIO_ID", "4954336430193681152"),
    "telegram_token":  os.environ.get("TELEGRAM_TOKEN", ""),
    "telegram_chat_id":os.environ.get("TELEGRAM_CHAT_ID", ""),
    "poll_interval":   int(os.environ.get("POLL_INTERVAL", "30")),
}
# =============================================

previous_positions = {}
monitor_active = False
monitor_thread = None

def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{CONFIG['telegram_token']}/sendMessage"
        payload = {
            "chat_id": CONFIG["telegram_chat_id"],
            "text": message,
            "parse_mode": "HTML"
        }
        r = requests.post(url, json=payload, timeout=10)
        return r.json()
    except Exception as e:
        print(f"[Telegram Error] {e}")
        return None

def get_leaderboard_positions():
    """Ambil posisi trader dari Binance Leaderboard"""
    try:
        portfolio_id = CONFIG["portfolio_id"]
        url = "https://www.binance.com/bapi/futures/v2/private/future/leaderboard/getOtherPosition"
        
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "clienttype": "web",
            "lang": "en"
        }
        
        payload = {
            "encryptedUid": portfolio_id,
            "tradeType": "PERPETUAL"
        }
        
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        data = r.json()
        
        if data.get("code") == "000000" and data.get("data"):
            positions = data["data"].get("otherPositionRetList", [])
            return {p["symbol"]: p for p in positions}
        
        # Coba endpoint alternatif
        url2 = "https://www.binance.com/bapi/futures/v1/public/future/leaderboard/getOtherPosition"
        r2 = requests.post(url2, json=payload, headers=headers, timeout=15)
        data2 = r2.json()
        
        if data2.get("code") == "000000" and data2.get("data"):
            positions = data2["data"].get("otherPositionRetList", [])
            return {p["symbol"]: p for p in positions}
            
        print(f"[Leaderboard] Response: {data}")
        return {}
        
    except Exception as e:
        print(f"[Error get_leaderboard_positions] {e}")
        return {}

def format_open(pos):
    side = "LONG 📈" if pos.get("amount", 0) > 0 else "SHORT 📉"
    symbol = pos.get("symbol", "?")
    entry = float(pos.get("entryPrice", 0))
    amount = abs(float(pos.get("amount", 0)))
    leverage = pos.get("leverage", "?")
    pnl = float(pos.get("pnl", 0))
    roe = float(pos.get("roe", 0)) * 100
    ts = datetime.now().strftime("%H:%M:%S")
    return (
        f"🟢 <b>OPEN {side}</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📌 <b>{symbol}</b>\n"
        f"💰 Entry: <b>${entry:,.4f}</b>\n"
        f"📦 Size: <b>{amount}</b>\n"
        f"⚡ Leverage: <b>{leverage}x</b>\n"
        f"📊 PnL: <b>${pnl:+.2f}</b> ({roe:+.2f}%)\n"
        f"🕐 {ts}"
    )

def format_close(prev):
    side = "LONG" if float(prev.get("amount", 0)) > 0 else "SHORT"
    symbol = prev.get("symbol", "?")
    entry = float(prev.get("entryPrice", 0))
    pnl = float(prev.get("pnl", 0))
    roe = float(prev.get("roe", 0)) * 100
    emoji = "✅" if pnl >= 0 else "❌"
    ts = datetime.now().strftime("%H:%M:%S")
    return (
        f"🔴 <b>CLOSE {side}</b> {emoji}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📌 <b>{symbol}</b>\n"
        f"💰 Entry was: <b>${entry:,.4f}</b>\n"
        f"📊 PnL: <b>${pnl:+.2f}</b> ({roe:+.2f}%)\n"
        f"🕐 {ts}"
    )

def format_size_change(pos, prev):
    old_amt = abs(float(prev.get("amount", 0)))
    new_amt = abs(float(pos.get("amount", 0)))
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
    current = get_leaderboard_positions()
    changes = []

    # Deteksi open posisi baru
    for symbol, pos in current.items():
        if symbol not in previous_positions:
            msg = format_open(pos)
            send_telegram(msg)
            changes.append({"type": "open", "symbol": symbol})
            print(f"[OPEN] {symbol}")
        else:
            prev = previous_positions[symbol]
            old_amt = abs(float(prev.get("amount", 0)))
            new_amt = abs(float(pos.get("amount", 0)))
            if abs(old_amt - new_amt) > 0.0001:
                msg = format_size_change(pos, prev)
                send_telegram(msg)
                changes.append({"type": "size_change", "symbol": symbol})
                print(f"[SIZE CHANGE] {symbol}")

    # Deteksi close posisi
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
    send_telegram("🤖 <b>Bot Monitor aktif!</b>\nMemantau posisi trader CopyTrade...")
    while monitor_active:
        check_positions()
        time.sleep(CONFIG['poll_interval'])
    send_telegram("⏹ <b>Bot Monitor dihentikan.</b>")

# =============================================
# API Endpoints
# =============================================

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

@app.route('/api/config', methods=['GET', 'POST'])
def config():
    if request.method == 'POST':
        data = request.json
        for key in ['telegram_token', 'telegram_chat_id', 'poll_interval', 'portfolio_id']:
            if key in data:
                CONFIG[key] = data[key]
        return jsonify({"success": True})
    safe = {k: (v[:6]+"****" if k in ['telegram_token'] else v)
            for k, v in CONFIG.items()}
    return jsonify(safe)

@app.route('/api/test/telegram', methods=['POST'])
def test_telegram():
    result = send_telegram("✅ <b>Test berhasil!</b>\nBot monitor terhubung ke Telegram.")
    if result and result.get('ok'):
        return jsonify({"success": True, "message": "Pesan test terkirim!"})
    return jsonify({"success": False, "message": str(result)})

@app.route('/api/debug')
def debug():
    positions = get_leaderboard_positions()
    return jsonify({
        "total": len(positions),
        "positions": list(positions.values())
    })

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
