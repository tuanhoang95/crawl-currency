import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime
import os
import re

def remove_accents(text):
    # Thay thế các ký tự có dấu thành không dấu
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

def scrape_phu_quy():
    url = "http://banggia.phuquygroup.vn/"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    source_id = "vang_phu_quy"
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')

        data = []
        table = soup.find('table')
        if not table:
            print("Không tìm thấy bảng giá Phú Quý")
            return

        rows = table.find_all('tr')
        for row in rows:
            cols = [c.get_text(strip=True) for c in row.find_all('td')]

            # Loại bỏ các cột rỗng ở đầu nếu có (tránh bị lệch index)
            while cols and not cols[0]:
                cols.pop(0)

            if len(cols) >= 3:
                product_name = cols[0]
                buy = cols[1]
                sell = cols[2]

                # Kiểm tra xem có phải dòng chứa giá tiền không
                if any(char.isdigit() for char in buy) or any(char.isdigit() for char in sell):
                    # Xác định loại tài sản
                    asset_type = "Vàng"
                    if "Bạc" in product_name:
                        asset_type = "Bạc"

                    # Đơn vị mặc định cho trang Phú Quý là Chỉ
                    unit = "Chỉ"

                    # Tạo product_id từ source_id và product_name (không dấu, lowercase, nối bằng _)
                    clean_name = remove_accents(product_name.lower())
                    # Xóa các ký tự đặc biệt chỉ giữ lại chữ cái, số và khoảng trắng
                    clean_name = re.sub(r'[^a-z0-9\s]', '', clean_name)
                    # Thay khoảng trắng bằng gạch dưới và xóa gạch dưới thừa
                    product_id = f"{source_id}_{clean_name.strip().replace(' ', '_')}"
                    product_id = re.sub(r'_+', '_', product_id)

                    data.append({
                        "product_id": product_id,
                        "asset_type": asset_type,
                        "product_name": product_name,
                        "unit": unit,
                        "buy": buy,
                        "sell": sell,
                        "currency": "VND"
                    })

        if not data:
            print("Không tìm thấy dữ liệu giá")
            return

        result = {
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": url,
            "source_id": source_id,
            "prices": data
        }

        # Lưu vào cùng thư mục với script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_path = os.path.join(script_dir, 'vang_phu_quy.json')

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"Thành công! Đã cập nhật vào {output_path}")

    except Exception as e:
        print(f"Lỗi Phú Quý: {e}")

if __name__ == "__main__":
    scrape_phu_quy()
