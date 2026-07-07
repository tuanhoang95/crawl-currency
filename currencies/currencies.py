import json
import os
import requests
from datetime import datetime

URL = "https://open.er-api.com/v6/latest/USD"
OUTPUT_FILE = "usd_rates.json"

def fetch_currencies():
    print(f"Fetching from {URL}...")
    try:
        response = requests.get(URL, timeout=30)
        response.raise_for_status()
        data = response.json()

        # Thêm thông tin thời gian cập nhật theo định dạng ISO
        data["last_updated_iso"] = datetime.now().astimezone().isoformat(timespec="seconds")

        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_path = os.path.join(script_dir, OUTPUT_FILE)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"Thành công! Đã lưu vào {output_path}")
        print(f"Cập nhật lúc: {data['last_updated_iso']}")
        print(f"Tỷ giá tiêu biểu: 1 USD = {data['rates'].get('VND')} VND")
    except Exception as e:
        print(f"Lỗi khi lấy dữ liệu: {e}")
        exit(1)

if __name__ == "__main__":
    fetch_currencies()
