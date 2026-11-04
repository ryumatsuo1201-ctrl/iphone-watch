"""Apple整備済iPhoneを監視し、指定価格以下の新着をメール通知する。"""
import json
import os
import re
import smtplib
from email.header import Header
from email.mime.text import MIMEText

import requests
from bs4 import BeautifulSoup

URL = "https://www.apple.com/jp/shop/refurbished/iphone"
MAX_PRICE = int(os.environ.get("MAX_PRICE") or 100000)
STATE_FILE = "notified.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "ja-JP,ja;q=0.9",
}


def normalize_url(href: str) -> str:
    href = href.split("?")[0]
    return "https://www.apple.com" + href if href.startswith("/") else href


def fetch_products() -> dict:
    """{商品URL: (商品名, 価格)} を返す"""
    html = requests.get(URL, headers=HEADERS, timeout=30).text
    products = {}

    # 1) ページに埋め込まれたJSONから取得
    m = re.search(r"window\.REFURB_GRID_BOOTSTRAP\s*=\s*(\{.*?\});\s*</script>", html, re.S)
    if m:
        try:
            for t in json.loads(m.group(1)).get("tiles", []):
                raw = t.get("price", {}).get("currentPrice", {}).get("raw_amount")
                href = t.get("productDetailsUrl", "")
                if raw and href:
                    products[normalize_url(href)] = (t.get("title", ""), int(float(raw)))
        except (ValueError, AttributeError):
            pass

    # 2) 取れなければHTMLから取得
    if not products:
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select('a[href*="/shop/product/"]'):
            title = a.get_text(strip=True)
            container = a.find_parent("li") or a.parent
            pm = re.search(r"([\d,]+)\s*円", container.get_text(" ", strip=True))
            if title and pm:
                products[normalize_url(a["href"])] = (title, int(pm.group(1).replace(",", "")))

    return products


def send_mail(items: list) -> None:
    body = "\n\n".join(f"{title}\n{price:,}円\n{url}" for url, title, price in items)
    msg = MIMEText(f"{body}\n\n一覧ページ: {URL}", "plain", "utf-8")
    msg["Subject"] = Header(f"【整備済iPhone】{MAX_PRICE:,}円以下が{len(items)}件出ました", "utf-8")
    msg["From"] = os.environ["SMTP_USER"]
    msg["To"] = os.environ["MAIL_TO"]
    with smtplib.SMTP_SSL(os.environ.get("SMTP_HOST") or "smtp.gmail.com", 465) as s:
        s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
        s.send_message(msg)


def main() -> None:
    products = fetch_products()
    print(f"取得件数: {len(products)}")
    if products:
        cheapest = min(p for _, p in products.values())
        print(f"最安値: {cheapest:,}円")

    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            notified = set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        notified = set()

    hits = [(u, t, p) for u, (t, p) in products.items() if p <= MAX_PRICE]
    new = [h for h in hits if h[0] not in notified]

    if new:
        send_mail(new)
        print(f"{len(new)}件を通知しました")

    # 掲載が消えた商品は記録から外す（再入荷したらまた通知される）
    updated = sorted((notified & products.keys()) | {u for u, _, _ in new})
    if set(updated) != notified:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(updated, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
