import json
from datetime import datetime
import os
import re
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

def remove_accents(text):
    accents = {'a': 'áàảãạăắằẳẵặâấầẩẫậ', 'A': 'ÁÀẢÃẠĂẮẰẲẴẶÂẤẦẨẪẬ', 'd': 'đ', 'D': 'Đ', 'e': 'éèẻẽẹêếềểễệ', 'E': 'ÉÈẺẼẸÊẾỀỂỄỆ', 'i': 'íìỉĩị', 'I': 'ÍÌỈĨỊ', 'o': 'óòỏõọôốồổỗộơớờởỡợ', 'O': 'ÓÒỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢ', 'u': 'úùủũụưứừửữự', 'U': 'ÚÙỦŨỤƯỨỪỬỮỰ', 'y': 'ýỳỷỹỵ', 'Y': 'ÝỲỶỸỴ'}
    for char, accented_chars in accents.items():
        for accented_char in accented_chars:
            text = text.replace(accented_char, char)
    return text

def scrape_silver():
    url = "https://btmc.vn/Home/BGiaBac"
    source_id = "bac_btmc"
    data = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36')
            print(f"Đang truy cập {url}...")
            page.goto(url, wait_until="networkidle")
            page.wait_for_selector("table")
            content = page.content()
            browser.close()

        soup = BeautifulSoup(content, 'html.parser')
        rows = soup.find_all('tr')
        current_brand = ""

        for row in rows:
            tds = row.find_all('td')
            if not tds: continue

            brand_td = row.find('td', rowspan=True)
            if brand_td:
                img = brand_td.find('img')
                src = img.attrs.get('src', '').lower() if img else ""
                current_brand = "btmc" if ('vrtl' in src or 'btm' in src) else "other"

            if current_brand != "btmc": continue

            cols = [t.get_text(" ", strip=True) for t in tds]
            # Bạc có 4 cột: Brand | Name | Buy | Sell
            if len(cols) == 4: # Hàng có cột brand
                product_name, buy, sell = cols[1], cols[2], cols[3]
            elif len(cols) == 3: # Hàng bị ẩn cột brand
                product_name, buy, sell = cols[0], cols[1], cols[2]
            else: continue

            # Chỉ lấy giá của BẠC RỒNG THĂNG LONG
            if "BAC RONG THANG LONG" not in remove_accents(product_name.upper()):
                continue

            if re.sub(r'[^\d]', '', buy + sell):
                clean_name = remove_accents(product_name.lower())
                product_id = f"{source_id}_{re.sub(r'[^a-z0-9]', '_', clean_name).strip('_')}"
                data.append({"product_id": re.sub(r'_+', '_', product_id), "asset_type": "Bạc", "product_name": product_name, "unit": "Lượng/Kg", "buy": buy, "sell": sell, "currency": "VND"})

        if data:
            result = {"last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "source": url, "source_id": source_id, "prices": data}
            with open(os.path.join(os.path.dirname(__file__), 'bac_btmc.json'), 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print(f"Thành công! Đã cập nhật Bạc BTMC ({len(data)} mã).")
    except Exception as e:
        print(f"Lỗi Bạc BTMC: {e}")

if __name__ == "__main__":
    scrape_silver()
