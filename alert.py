import json
import os
import sys
import time
import urllib.parse
import urllib.request

# These come from GitHub Secrets, never written in the code
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")  # like @pumpradar_alerts

# Settings you can change later
THRESHOLD = 5.0          # alert when a coin is up this % in the last hour
COOLDOWN_HOURS = 6       # don't alert about the same coin again within this time
MAX_ALERTS_PER_RUN = 5   # avoid flooding the channel
STATE_FILE = "state.json"


def http_get_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": "PumpRadar/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": CHANNEL_ID,
        "text": text,
        "disable_web_page_preview": "true",
    }).encode()
    with urllib.request.urlopen(url, data=data, timeout=20) as response:
        return json.load(response)


def get_movers():
    """Top 100 coins by market cap that are up at least THRESHOLD% in 1 hour."""
    url = (
        "https://api.coingecko.com/api/v3/coins/markets"
        "?vs_currency=usd&order=market_cap_desc&per_page=100&page=1"
        "&price_change_percentage=1h"
    )
    coins = http_get_json(url)
    movers = []
    for coin in coins:
        change = coin.get("price_change_percentage_1h_in_currency")
        if change is not None and change >= THRESHOLD:
            movers.append((change, coin))
    movers.sort(key=lambda item: item[0], reverse=True)
    return movers


def format_price(price):
    if price < 1:
        return f"${price:.6f}"
    return f"${price:,.2f}"


def build_message(change, coin):
    return (
        f"🚀 PumpRadar: {coin['name']} ({coin['symbol'].upper()})\n"
        f"+{change:.1f}% in the last hour\n"
        f"Price: {format_price(coin['current_price'])}\n\n"
        "Not financial advice. Always do your own research."
    )


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)


def main():
    if not BOT_TOKEN or not CHANNEL_ID:
        sys.exit("BOT_TOKEN and CHANNEL_ID must be set as GitHub Secrets.")

    mode = sys.argv[1] if len(sys.argv) > 1 else "scan"

    if mode == "test":
        send_telegram("✅ PumpRadar is connected and ready.")
        print("Test message sent.")
        return

    now = time.time()
    state = load_state()
    # Forget alerts older than 24 hours so the file stays small
    state = {coin_id: ts for coin_id, ts in state.items() if now - ts < 24 * 3600}

    try:
        movers = get_movers()
    except Exception as error:
        print(f"Could not fetch prices this time: {error}")
        save_state(state)
        return

    sent = 0
    for change, coin in movers:
        if sent >= MAX_ALERTS_PER_RUN:
            break
        last_alert = state.get(coin["id"])
        if last_alert and now - last_alert < COOLDOWN_HOURS * 3600:
            continue
        try:
            send_telegram(build_message(change, coin))
        except Exception as error:
            print(f"Could not send alert: {error}")
            break
        state[coin["id"]] = now
        sent += 1

    save_state(state)
    print(f"Checked {len(movers)} movers, sent {sent} alerts.")


if __name__ == "__main__":
    main()
