"""
Binance CopyTrade Position Monitor - Backend Server
Jalankan: pip install flask flask-cors python-binance requests
Lalu: python server.py
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
from binance.client import Client
import requests
import json
import time
import threading
import hashlib
import hmac
import os
from datetime import datetime

app = Flask(__name__)
CORS(app)

# =============================================
# KONFIGURASI — diisi lewat Railway Environment Variables
# =============================================
CONFIG = {
    "binance_api_key": os.environ.get("BINANCE_API_KEY", ""),
    "binance_secret":  os.environ.get("BINANCE_SECRET", ""),
    "telegram_token":  os.environ.get("TELEGRAM_TOKEN", ""),
    "telegram_chat_id":os.environ.get("TELEGRAM_CHAT_ID", ""),
    "poll_interval":   int(os.environ.get("POLL_INTERVAL", "15")),
    "testnet":         False
}
# =============================================

# State penyimpanan posisi sebelumnya
previous_positions = {}
monitor_active = False
monitor_thread = None

def get_client():
    return Client(CONFIG["binance_api_key"], CONFIG["binance_secret"],
                  testnet=CONFIG["testnet"])

def send_telegram(message):
    """Kirim pesan ke Telegram"""
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

def format_position_open(pos):
    side = "LONG 📈" if float(pos['positionAmt']) > 0 else "SHORT 📉"
    amt  = abs(float(pos['positionAmt']))
    entry = float(pos['entryPrice'])
    pnl   = float(pos.get('unrealizedProfit', 0))
    lev   = pos.get('leverage', '?')
    symbol = pos['symbol']
    ts = datetime.now().strftime("%H:%M:%S")

    return (
        f"🟢 <b>OPEN {side}</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📌 <b>{symbol}</b>\n"
        f"💰 Entry: <b>${entry:,.4f}</b>\n"
        f"📦 Size: <b>{amt}</b>\n"
        f"⚡ Leverage: <b>{lev}x</b>\n"
        f"📊 uPnL: <b>${pnl:+.2f}</b>\n"
        f"🕐 {ts}"
    )

def format_position_close(pos, prev):
    side = "LONG" if float(prev['positionAmt']) > 0 else "SHORT"
    pnl  = float(prev.get('unrealizedProfit', 0))
    emoji = "✅" if pnl >= 0 else "❌"
    symbol = prev['symbol']
    entry  = float(prev['entryPrice'])
    ts = datetime.now().strftime("%H:%M:%S")

    return (
        f"🔴 <b>CLOSE {side}</b> {emoji}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📌 <b>{symbol}</b>\n"
        f"💰 Entry was: <b>${entry:,.4f}</b>\n"
        f"📊 PnL akhir: <b>${pnl:+.2f}</b>\n"
        f"🕐 {ts}"
    )

def format_size_change(pos, prev):
    old_amt = abs(float(prev['positionAmt']))
    new_amt = abs(float(pos['positionAmt']))
    diff    = new_amt - old_amt
    direction = "➕ Tambah size" if diff > 0 else "➖ Kurang size"
    symbol = pos['symbol']
    ts = datetime.now().strftime("%H:%M:%S")

    return (
        f"🔄 <b>{direction}</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📌 <b>{symbol}</b>\n"
        f"📦 {old_amt} → <b>{new_amt}</b> ({diff:+.4f})\n"
        f"🕐 {ts}"
    )

def check_positions():
    """Ambil posisi aktif dari Binance Futures"""
    global previous_positions
    try:
        client = get_client()
        positions = client.futures_position_information()
        # Filter hanya yang ada posisi aktif
        active = {p['symbol']: p for p in positions if abs(float(p['positionAmt'])) > 0}

        changes = []

        # Deteksi open posisi baru
        for symbol, pos in active.items():
            if symbol not in previous_positions:
                msg = format_position_open(pos)
                send_telegram(msg)
                changes.append({"type": "open", "symbol": symbol, "position": pos})
                print(f"[OPEN] {symbol}")

            else:
                prev = previous_positions[symbol]
                old_amt = abs(float(prev['positionAmt']))
                new_amt = abs(float(pos['positionAmt']))
                if abs(old_amt - new_amt) > 0.0001:
                    msg = format_size_change(pos, prev)
                    send_telegram(msg)
                    changes.append({"type": "size_change", "symbol": symbol})
                    print(f"[SIZE CHANGE] {symbol}")

        # Deteksi close posisi
        for symbol, prev in previous_positions.items():
            if symbol not in active:
                msg = format_position_close(None, prev)
                send_telegram(msg)
                changes.append({"type": "close", "symbol": symbol})
                print(f"[CLOSE] {symbol}")

        previous_positions = active
        return active, changes

    except Exception as e:
        print(f"[Error check_positions] {e}")
        return {}, []

def monitor_loop():
    global monitor_active
    print(f"[Monitor] Mulai polling setiap {CONFIG['poll_interval']} detik...")
    send_telegram("🤖 <b>Bot Monitor aktif!</b>\nMemantau posisi CopyTrade kamu...")
    while monitor_active:
        check_positions()
        time.sleep(CONFIG['poll_interval'])
    send_telegram("⏹ <b>Bot Monitor dihentikan.</b>")

# =============================================
# API Endpoints untuk dashboard HTML
# =============================================

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
        for key in ['binance_api_key', 'binance_secret', 'telegram_token', 'telegram_chat_id', 'poll_interval']:
            if key in data:
                CONFIG[key] = data[key]
        return jsonify({"success": True})
    # GET — jangan return secret key secara penuh
    safe = {k: (v[:6]+"****" if k in ['binance_api_key','binance_secret','telegram_token'] else v)
            for k, v in CONFIG.items()}
    return jsonify(safe)

@app.route('/api/copytrade')
def copytrade():
    try:
        client = get_client()
        result = client._request_futures_api(
            'get', 'copyTrading/futures/position', True
        )
        return jsonify({"raw": result})
    except Exception as e:
        try:
            result2 = client._request_margin_api(
                'get', 'copyTrading/futures/position', True
            )
            return jsonify({"raw2": result2})
        except Exception as e2:
            return jsonify({
                "error1": str(e),
                "error2": str(e2)
            })


@app.route('/api/debug')
def debug():
    try:
        client = get_client()
        positions = client.futures_position_information()
        account = client.futures_account()
        return jsonify({
            "total_positions": len(positions),
            "active": [p for p in positions if float(p['positionAmt']) != 0],
            "totalWalletBalance": account.get('totalWalletBalance'),
            "totalUnrealizedProfit": account.get('totalUnrealizedProfit')
        })
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/api/myip')
def myip():
    import urllib.request
    ip = urllib.request.urlopen('https://api.ipify.org').read().decode()
    return jsonify({"ip": ip})

@app.route('/api/test/telegram', methods=['POST'])
def test_telegram():
    result = send_telegram("✅ <b>Test berhasil!</b>\nBot monitor terhubung ke Telegram.")
    if result and result.get('ok'):
        return jsonify({"success": True, "message": "Pesan test terkirim!"})
    return jsonify({"success": False, "message": str(result)})

if __name__ == '__main__':
    print("=" * 50)
    print("  Binance CopyTrade Monitor")
    print("  http://localhost:5000")
    print("=" * 50)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

@app.route('/api/myip')
def myip():
    import urllib.request
    ip = urllib.request.urlopen('https://api.ipify.org').read().decode()
    return jsonify({"ip": ip})
    
@app.route('/api/debug')
def debug():
    try:
        client = get_client()
        # Coba ambil semua posisi termasuk yang size 0
        positions = client.futures_position_information()
        account = client.futures_account()
        return jsonify({
            "total_positions": len(positions),
            "active": [p for p in positions if float(p['positionAmt']) != 0],
            "totalWalletBalance": account.get('totalWalletBalance'),
            "totalUnrealizedProfit": account.get('totalUnrealizedProfit')
        })
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/api/copytrade')
def copytrade():
    try:
        client = get_client()
        # Coba endpoint portfolio margin / copytrading
        result = client._request_futures_api(
            'get', 'copyTrading/futures/position', True
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)})
