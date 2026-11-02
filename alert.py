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
THRESHOLD = 5.0               # alert when a coin is up this % in the last hour
COOLDOWN_HOURS = 6            # don't alert about the same coin again within this time
MAX_ALERTS_PER_RUN = 5        # avoid flooding the channel
DIGEST_INTERVAL_MINUTES = 60  # how often to post the regular price update
DIGEST_COIN_COUNT = 10        # how many top coins to show in the price update
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


def get_market():
    """Top 100 coins by market cap, with 1 hour and 24 hour price changes."""
    url = (
        "https://api.coingecko.com/api/v3/coins/markets"
        "?vs_currency=usd&order=market_cap_desc&per_page=100&page=1"
        "&price_change_percentage=1h,24h"
    )
    return http_get_json(url)


def find_movers(coins):
    """Coins up at least THRESHOLD% in 1 hour, biggest first."""
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


def format_change(value):
    if value is None:
        return "n/a"
    return f"{value:+.1f}%"


def build_alert(change, coin):
    return (
        f"🚀 PumpRadar: {coin['name']} ({coin['symbol'].upper()})\n"
        f"+{change:.1f}% in the last hour\n"
        f"Price: {format_price(coin['current_price'])}\n\n"
        "Not financial advice. Always do your own research."
    )


def build_digest(coins):
    lines = ["📊 PumpRadar price update", ""]
    for coin in coins[:DIGEST_COIN_COUNT]:
        change_1h = coin.get("price_change_percentage_1h_in_currency")
        change_24h = coin.get("price_change_percentage_24h_in_currency")
        icon = "🟢" if (change_1h or 0) >= 0 else "🔴"
        lines.append(
            f"{icon} {coin['symbol'].upper()} {format_price(coin['current_price'])}"
            f"  1h {format_change(change_1h)} | 24h {format_change(change_24h)}"
        )
    lines += ["", "Not financial advice."]
    return "\n".join(lines)


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
        # Manual run: confirm the connection and show a sample price update
        send_telegram("✅ PumpRadar is connected and ready.")
        try:
            send_telegram(build_digest(get_market()))
        except Exception as error:
            print(f"Could not post the price update: {error}")
        print("Test finished.")
        return

    now = time.time()
    state = load_state()
    last_digest = state.pop("_last_digest", 0)
    # Forget alerts older than 24 hours so the file stays small
    state = {coin_id: ts for coin_id, ts in state.items() if now - ts < 24 * 3600}

    try:
        coins = get_market()
    except Exception as error:
        print(f"Could not fetch prices this time: {error}")
        state["_last_digest"] = last_digest
        save_state(state)
        return

    # 1) Pump alerts
    sent = 0
    for change, coin in find_movers(coins):
        if sent >= MAX_ALERTS_PER_RUN:
            break
        last_alert = state.get(coin["id"])
        if last_alert and now - last_alert < COOLDOWN_HOURS * 3600:
            continue
        try:
            send_telegram(build_alert(change, coin))
        except Exception as error:
            print(f"Could not send alert: {error}")
            break
        state[coin["id"]] = now
        sent += 1

    # 2) Regular price update (checked every run, posted when it's due)
    # The "- 4" lets the update go out on the run closest to the hour mark
    if now - last_digest >= (DIGEST_INTERVAL_MINUTES - 4) * 60:
        try:
            send_telegram(build_digest(coins))
            last_digest = now
            print("Posted price update.")
        except Exception as error:
            print(f"Could not post price update: {error}")

    state["_last_digest"] = last_digest
    save_state(state)
    print(f"Sent {sent} alerts.")


if __name__ == "__main__":
    main()

