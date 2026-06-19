import requests
import json
import time
import os
import sys
import random

DISCORD_WEBHOOK = "YOUR_DISCORD_WEBHOOK" # <----- change ts if u want logs.

def send_discord(message):
    if "YOUR_DISCORD_WEBHOOK" in DISCORD_WEBHOOK:
        print("No notifications set")
        return
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": message}, timeout=10)
        print(f"Discord sent: {message}")
    except Exception as e:
        print(f"Discord error: {e}")

BAZAAR_URL = "https://blacket.org/worker/bazaar"
BUY_URL = "https://blacket.org/worker/bazaar/buy"
SELL_URL = "https://blacket.org/worker/sell"
BLACKET_LOGIN_URL = "https://blacket.org/worker/login"

BOUGHT_FILE = "bought.txt"
LOGIC_FILE = "logic.json"
BLACKLIST_FILE = "blacklist.txt"
ACCOUNTS_FILE = "accounts.txt"

poll_interval = 1
profit_report_interval = 1200

class Account:
    def __init__(self, username=None, password=None, cookies=None):
        self.username = username
        self.password = password
        self.cookies = cookies or {}
        self.session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(max_retries=3)
        self.session.mount('https://', adapter)
        self.session.mount('http://', adapter)

accounts = []
current_account_index = 0

def parse_account_line(line):
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    parts = [part.strip() for part in line.split(";") if part.strip()]
    username = None
    password = None
    cookies = {}

    first = parts[0]
    if ":" in first and not first.lower().startswith("blacketauth=") and not first.lower().startswith("blackettoken="):
        username, password = first.split(":", 1)
        for part in parts[1:]:
            if "=" in part:
                k, v = [x.strip() for x in part.split("=", 1)]
                cookies[k] = v
    else:
        for part in parts:
            if "=" in part:
                k, v = [x.strip() for x in part.split("=", 1)]
                cookies[k] = v

    return Account(username=username, password=password, cookies=cookies)


def save_account_cookie_to_file(account):
    if not account.username or not account.password or not account.cookies:
        return

    cookie_str = ";".join(f"{k}={v}" for k, v in account.cookies.items())
    target_line = f"{account.username}:{account.password};{cookie_str}"

    try:
        if not os.path.exists(ACCOUNTS_FILE):
            return

        with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()

        updated = False
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith(f"{account.username}:"):
                lines[idx] = target_line + "\n"
                updated = True
                break

        if not updated:
            lines.append(target_line + "\n")

        with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
            f.writelines(lines)

        print(f"Saved auth cookie for {account.username} to {ACCOUNTS_FILE}")
    except Exception as e:
        print(f"Error saving account cookie: {e}")


LOGIN_HEADERS = {
    "Host": "blacket.org",
    "Sec-Ch-Ua-Platform": "Windows",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Ch-Ua": '"Not_A Brand";v="99", "Chromium";v="142"',
    "Sec-Ch-Ua-Mobile": "?0",
    "X-Requested-With": "XMLHttpRequest",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Content-Type": "application/json",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "Referer": "https://blacket.org/login",
    "Accept-Encoding": "gzip, deflate",
    "Priority": "u=1, i"
}

def attempt_login(username, password):
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(max_retries=3)
    session.mount('https://', adapter)
    session.mount('http://', adapter)

    payload = {"username": username, "password": password}
    try:
        response = session.post(BLACKET_LOGIN_URL, headers=LOGIN_HEADERS, json=payload,timeout=15)
        if response.status_code != 200:
            print(f"Login HTTP {response.status_code} for {username}")
            return None

        try:
            json_data = response.json()
        except ValueError:
            print(f"Login response not JSON for {username}")
            return None

        if json_data.get("error"):
            print(f"Login rejected for {username}: {json_data.get('reason')}")
            return None

        cookies = session.cookies.get_dict()
        if not cookies:
            set_cookie = response.headers.get("Set-Cookie", "")
            for part in set_cookie.split(";"):
                if "=" in part:
                    k, v = [x.strip() for x in part.split("=", 1)]
                    if k and v:
                        cookies[k] = v

        return cookies if cookies else None
    except Exception as e:
        print(f"Login error for {username}: {e}")
        return None


def login_account(account):
    if not account.username or not account.password:
        return False
    if account.cookies:
        return True

    cookies = attempt_login(account.username, account.password)
    if not cookies:
        print(f"Login failed for {account.username}")
        return False

    account.cookies = cookies
    save_account_cookie_to_file(account)
    print(f"Logged in {account.username} and stored auth cookie")
    return True

HEADERS = {
    "authority": "blacket.org",
    "accept": "*/*",
    "accept-encoding": "identity",
    "accept-language": "en-US,en;q=0.9",
    "content-type": "application/json",
    "origin": "https://blacket.org",
    "priority": "u=1, i",
    "referer": "https://blacket.org/blooks/",
    "sec-ch-ua": '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "x-requested-with": "XMLHttpRequest",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
}

blooks = {}
blacklist = set()
saved_good = set()
saved_bought = set()

total_profit = 0
last_report_time = time.time()

NO_SELL_RARITIES = {"Chroma", "Mythical", "Iridescent"}

def load_accounts():
    global accounts
    if not os.path.exists(ACCOUNTS_FILE):
        print(f"ERROR: {ACCOUNTS_FILE} not found")
        print("Create accounts.txt with one user:password per line")
        sys.exit(1)

    with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            parsed = parse_account_line(line)
            if parsed is None:
                continue
            accounts.append(parsed)

    print(f"Loaded {len(accounts)} accounts.")

    for account in accounts:
        if account.username and account.password and not account.cookies:
            login_account(account)

def get_next_account():
    global current_account_index
    if not accounts:
        return None
    acc = accounts[current_account_index]
    current_account_index = (current_account_index + 1) % len(accounts)
    return acc

def load_logic():
    global blooks
    if os.path.exists(LOGIC_FILE):
        try:
            with open(LOGIC_FILE, "r", encoding="utf-8") as f:
                blooks = json.load(f)
            print(f"Loaded {len(blooks)} blooks from {LOGIC_FILE}.")
        except Exception as e:
            print(f"Error loading {LOGIC_FILE}: {e}")

def load_blacklist():
    global blacklist
    if os.path.exists(BLACKLIST_FILE):
        try:
            with open(BLACKLIST_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    name = line.strip().strip('"').strip("'")
                    if name:
                        blacklist.add(name)
            print(f"Loaded {len(blacklist)} blacklisted blooks.")
        except Exception as e:
            print(f"Error loading blacklist: {e}")

def load_saved():
    global saved_good, saved_bought
    for file_path, target_set in [(BOUGHT_FILE, saved_bought)]:
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        target_set.add(line.strip())

def save_bought(line):
    if line in saved_bought: return
    with open(BOUGHT_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    saved_bought.add(line)
    print(f"BOUGHT SAVED: {line}")

def is_good_deal(item_name, listing_price):
    blook = blooks.get(item_name)
    if not blook:
        return False, "Unknown blook"
    raw_sell = blook.get("price", 0)
    if raw_sell == 0:
        return False, "No price"
    profit = raw_sell - listing_price
    if profit > 0:
        return True, f"PROFIT {profit} tokens (buy {listing_price} → raw {raw_sell})"
    return False, f"No profit ({listing_price}/{raw_sell})"

def raw_sell(account, blook_name, buy_price):
    global total_profit
    payload = {"blook": blook_name, "quantity": "1"}
    try:
        response = account.session.post(SELL_URL, headers=HEADERS, cookies=account.cookies,
                                      json=payload, timeout=60)
        if response.status_code == 200:
            data = response.json()
            if not data.get("error"):
                raw_price = blooks.get(blook_name, {}).get("price", buy_price)
                profit = raw_price - buy_price
                total_profit += profit
                account_name = account.username or "Unknown"
                msg = f"[{account_name}] Raw sold {blook_name} for {raw_price} (+{profit})"
                send_discord(msg)
                return True
    except Exception as e:
        print(f"Raw sell error: {e}")
    return False

def buy_listing(account, listing_id, full_line, blook_name, price):
    payload = {"id": listing_id}
    try:
        response = account.session.post(BUY_URL, headers=HEADERS, cookies=account.cookies,
                                      json=payload, timeout=60)
        if response.status_code == 200:
            data = response.json()
            if not data.get("error"):
                print(f"Bought {full_line}")
                save_bought(full_line)
                account_name = account.username or "Unknown"
                send_discord(f"[{account_name}] Bought {blook_name} for {price} tokens")
                
                if blook_name in blacklist or blooks.get(blook_name, {}).get("rarity") in NO_SELL_RARITIES:
                    send_discord(f"[{account_name}] Keeping {blook_name} (protected)")
                    return True
                
                time.sleep(random.uniform(20, 40))
                raw_sell(account, blook_name, price)
                return True
    except Exception as e:
        print(f"Buy error: {e}")
    return False

def fetch_bazaar(account):
    try:
        response = account.session.get(BAZAAR_URL, headers=HEADERS, cookies=account.cookies,
                                    timeout=60)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict) and data.get("error"):
            if "unauthorized" in str(data.get("reason", "")).lower():
                print(f"Account cookie expired")
                return None
            print(f"API Error: {data.get('reason')}")
            return None
        return data.get("bazaar", [])
    except Exception as e:
        print(f"Fetch error: {e}")
        return None

def process_listings():
    global last_report_time
    account = get_next_account()
    if not account:
        print("No accounts loaded!")
        return

    listings = fetch_bazaar(account)
    if listings is None:
        return

    print(f"Fetched {len(listings)} listings | Account #{accounts.index(account)+1}")

    for listing in listings:
        item = listing.get("item", "unknown")
        price = listing.get("price", 0)
        listing_id = listing.get("id")
        if listing_id is None:
            continue

        base_line = f"{listing.get('seller', 'unknown')}:{item}:{price}"
        full_line = base_line + f" (ID: {listing_id})"
        if item in blooks:
            full_line += f" [{blooks[item].get('rarity', 'Unknown')}]"

        is_deal, reason = is_good_deal(item, price)
        if is_deal:
            account_name = account.username or "Unknown"
            send_discord(f"[{account_name}] Profit: {reason}")
            print(f"Buying Blook")
            time.sleep(1)
            buy_listing(account, listing_id, full_line, item, price)

    if time.time() - last_report_time >= profit_report_interval:
        send_discord(f"Total profit so far: {total_profit} tokens")
        last_report_time = time.time()

load_accounts()
print("")

try:
    while True:
        process_listings()
        time.sleep(poll_interval)
except KeyboardInterrupt:
    print("\nStopped.")
