import json
from datetime import datetime
import os
import re
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

def remove_accents(text):
    accents = {
        'a': 'áàảãạăắằẳẵặâấầẩẫậ',
        'A': 'ÁÀẢÃẠĂẮẰẲẴẶÂẤẦẨẪẬ',
        'd': 'đ',
        'D': 'Đ',
        'e': 'éèẻẽẹêếềểễệ',
        'E': 'ÉÈẺẼẸÊẾỀỂỄỆ',
        'i': 'íìỉĩị',
        'I': 'ÍÌỈĨỊ',
        'o': 'óòỏõọôốồổỗộơớờởỡợ',
        'O': 'ÓÒỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢ',
        'u': 'úùủũụưứừửữự',
        'U': 'ÚÙỦŨỤƯỨỪỬỮỰ',
        'y': 'ýỳỷỹỵ',
        'Y': 'ÝỲỶỸỴ'
    }
    for char, accented_chars in accents.items():
        for accented_char in accented_chars:
            text = text.replace(accented_char, char)
    return text

def scrape_btmc():
    url = "https://btmc.vn/Home/BGiaVang"
    source_id = "vang_btmc"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
            )
            page = context.new_page()
            print(f"Đang truy cập {url}...")
            page.goto(url, wait_until="networkidle", timeout=30000)
            page.wait_for_selector("table", timeout=10000)
            content = page.content()
            browser.close()

        soup = BeautifulSoup(content, 'html.parser')
        data = []

        table = soup.find('table', class_='bd_price_home')
        if not table:
            table = soup.find('table')

        if not table:
            print("Không tìm thấy bảng giá.")
            return

        rows = table.find_all('tr')
        for row in rows:
            # Lấy các ô td trong hàng
            tds = row.find_all('td')
            if not tds:
                continue

            cols = [t.get_text(" ", strip=True) for t in tds]

            # Cấu trúc:
            # 5 cột: Thương phẩm | Loại vàng | Hàm lượng | Mua vào | Bán ra
            # 4 cột: Loại vàng | Hàm lượng | Mua vào | Bán ra (do Thương phẩm bị rowspan)

            if len(cols) == 5:
                product_name = cols[1]
                buy = cols[3]
                sell = cols[4]
            elif len(cols) == 4:
                product_name = cols[0]
                buy = cols[2]
                sell = cols[3]
            else:
                continue

            # Chỉ lấy hàng có giá trị số trong cột mua/bán
            buy_clean = re.sub(r'[^\d]', '', buy)
            sell_clean = re.sub(r'[^\d]', '', sell)

            if buy_clean or sell_clean:
                # Tạo ID
                clean_name = remove_accents(product_name.lower())
                clean_name = re.sub(r'[^a-z0-9\s]', '', clean_name)
                product_id = f"{source_id}_{clean_name.strip().replace(' ', '_')}"
                product_id = re.sub(r'_+', '_', product_id)

                data.append({
                    "product_id": product_id,
                    "asset_type": "Vàng", # Mặc định là vàng cho trang này
                    "product_name": product_name,
                    "unit": "Chỉ",
                    "buy": buy,
                    "sell": sell,
                    "currency": "VND"
                })

        if not data:
            print("Không tìm thấy dữ liệu.")
            return

        # Loại bỏ trùng lặp
        unique_data = []
        seen_ids = set()
        for item in data:
            if item['product_id'] not in seen_ids:
                unique_data.append(item)
                seen_ids.add(item['product_id'])

        result = {
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": url,
            "source_id": source_id,
            "prices": unique_data
        }

        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_path = os.path.join(script_dir, 'vang_btmc.json')

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        print(f"Thành công! Đã lấy được {len(unique_data)} sản phẩm.")

    except Exception as e:
        print(f"Lỗi: {e}")

if __name__ == "__main__":
    scrape_btmc()
