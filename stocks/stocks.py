from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from bs4 import BeautifulSoup
from playwright.sync_api import Browser, Page, TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


SOURCE_ID = "chung_khoan_vietstock"
OUTPUT_FILE = "chung_khoan_vietstock.json"

EXCHANGE_URLS = {
    "HOSE": "https://banggia.vietstock.vn/bang-gia/hose",
    "HNX": "https://banggia.vietstock.vn/bang-gia/hnx",
    "UPCOM": "https://banggia.vietstock.vn/bang-gia/upcom",
}

# Giá trên bảng Vietstock có đơn vị: x 1.000 VND.
PRICE_MULTIPLIER = 1000

# None = không giới hạn số mã.
MAX_STOCKS: int | None = None

# Thời gian chờ trang chạy JavaScript lần đầu.
INITIAL_WAIT_MS = 5_000

# Thời gian chờ sau mỗi lần cuộn.
SCROLL_WAIT_MS = 700

# Số vòng cuộn tối đa cho mỗi sàn.
MAX_SCROLL_ROUNDS = 180

# Dừng nếu nhiều vòng liên tiếp không xuất hiện mã mới.
MAX_STABLE_ROUNDS = 12

# Nếu cuộn vẫn lấy được quá ít mã, thử ô tìm kiếm theo tiền tố.
ENABLE_PREFIX_FALLBACK = True
PREFIX_WAIT_MS = 120

# Giới hạn thường thấy của HTML ban đầu.
PAGE_BATCH_SIZE = 30

EXCHANGES = {
    "HOSE",
    "HSX",
    "HNX",
    "UPCOM",
}

RESERVED_WORDS = {
    "HNX",
    "HSX",
    "VND",
    "VNI",
    "ATO",
    "ATC",
    "PLO",
}

SYMBOL_PATTERN = re.compile(
    r"^(?P<symbol>[A-Z][A-Z0-9]{2})"
    r"(?P<flags>\*{0,2})"
    r"(?:\s+(?P<name>.+))?$"
)

PRICE_PATTERN = re.compile(
    r"^[+\-−–—]?\d+(?:[.,]\d+)?$"
)

PERCENT_PATTERN = re.compile(
    r"^[+\-−–—]?\d+(?:[.,]\d+)?%$"
)


def normalize_text(value: str | None) -> str:
    if value is None:
        return ""

    return re.sub(
        r"\s+",
        " ",
        value.replace("\xa0", " "),
    ).strip()


def normalize_number_text(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = (
        normalize_text(value)
        .replace("−", "-")
        .replace("–", "-")
        .replace("—", "-")
    )

    if normalized in {
        "",
        "-",
        "--",
        "---",
    }:
        return None

    return normalized


def is_price_text(value: str | None) -> bool:
    normalized = normalize_number_text(value)

    if normalized is None:
        return False

    return (
        PRICE_PATTERN.fullmatch(normalized)
        is not None
    )


def is_percent_text(value: str | None) -> bool:
    normalized = normalize_number_text(value)

    if normalized is None:
        return False

    return (
        PERCENT_PATTERN.fullmatch(normalized)
        is not None
    )


def parse_decimal(
    value: str | None,
) -> Decimal | None:
    normalized = normalize_number_text(value)

    if normalized is None:
        return None

    normalized = (
        normalized
        .rstrip("%")
        .strip()
    )

    # Giá Vietstock dùng dấu chấm cho phần thập phân:
    # 23.05 = 23,05 nghìn VND.
    #
    # Khối lượng thường dùng dấu phẩy, nhưng hàm này
    # chỉ được dùng cho các cột giá và phần trăm.
    if (
        "," in normalized
        and "." not in normalized
    ):
        normalized = normalized.replace(
            ",",
            ".",
        )
    else:
        normalized = normalized.replace(
            ",",
            "",
        )

    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None


def decimal_to_number(
    value: Decimal | None,
) -> int | float | None:
    if value is None:
        return None

    if value == value.to_integral_value():
        return int(value)

    return float(value)


def convert_price_to_vnd(
    raw_price: Decimal | None,
) -> int | None:
    """
    Ví dụ:

        current_raw = 23.05
        current = 23.05 × 1000
        current = 23_050 VND/cổ phiếu
    """

    if raw_price is None:
        return None

    result = (
        raw_price * PRICE_MULTIPLIER
    ).quantize(
        Decimal("1"),
        rounding=ROUND_HALF_UP,
    )

    return int(result)


def extract_symbol_and_name(
    value: str,
) -> tuple[str, str | None, str] | None:
    normalized = normalize_text(value)

    match = SYMBOL_PATTERN.fullmatch(
        normalized
    )

    if not match:
        return None

    symbol = match.group("symbol").upper()

    if symbol in RESERVED_WORDS:
        return None

    name = normalize_text(
        match.group("name")
    )

    return (
        symbol,
        name or None,
        match.group("flags") or "",
    )


def get_value(
    values: list[str],
    index: int,
) -> str | None:
    if (
        index < 0
        or index >= len(values)
    ):
        return None

    value = normalize_text(
        values[index]
    )

    return value or None


def find_first_price_triplet(
    values: list[str],
) -> int | None:
    """
    Tìm ba cột giá đầu tiên:

        tham chiếu, trần, sàn
    """

    for index in range(
        0,
        max(0, len(values) - 2),
    ):
        if (
            is_price_text(values[index])
            and is_price_text(
                values[index + 1]
            )
            and is_price_text(
                values[index + 2]
            )
        ):
            return index

    return None


def build_stock_item(
    *,
    symbol: str,
    product_name: str | None,
    exchange: str,
    flags: str,
    quote_cells: list[str],
    source_url: str,
) -> dict[str, Any] | None:
    """
    Cấu trúc chuẩn của các cột sau mã và tên:

      0  tham chiếu
      1  trần
      2  sàn
      3  giá mua 3
      4  KL mua 3
      5  giá mua 2
      6  KL mua 2
      7  giá mua 1
      8  KL mua 1
      9  giá khớp hiện tại
     10  KL khớp
     11  thay đổi
     12  phần trăm thay đổi

    Một số dòng không giao dịch có thể thiếu nhiều ô.
    """

    if len(quote_cells) < 3:
        return None

    reference_raw = parse_decimal(
        get_value(quote_cells, 0)
    )
    ceiling_raw = parse_decimal(
        get_value(quote_cells, 1)
    )
    floor_raw = parse_decimal(
        get_value(quote_cells, 2)
    )

    current_raw = parse_decimal(
        get_value(quote_cells, 9)
    )
    change_raw = parse_decimal(
        get_value(quote_cells, 11)
    )
    change_percent = parse_decimal(
        get_value(quote_cells, 12)
    )

    # Khi HTML bỏ các ô rỗng, chỉ số cột có thể bị dịch.
    # Tìm cặp thay đổi + phần trăm để suy ra giá khớp.
    percent_index: int | None = None

    for index, value in enumerate(
        quote_cells[3:],
        start=3,
    ):
        if is_percent_text(value):
            percent_index = index
            break

    if (
        percent_index is not None
        and percent_index >= 2
    ):
        possible_change = parse_decimal(
            get_value(
                quote_cells,
                percent_index - 1,
            )
        )
        possible_current = parse_decimal(
            get_value(
                quote_cells,
                percent_index - 2,
            )
        )
        possible_percent = parse_decimal(
            get_value(
                quote_cells,
                percent_index,
            )
        )

        if possible_current is not None:
            current_raw = possible_current

        if possible_change is not None:
            change_raw = possible_change

        if possible_percent is not None:
            change_percent = possible_percent

    current_source = "last_match"

    # Mã chưa có giao dịch trong phiên:
    # dùng giá tham chiếu để current không bị null,
    # đồng thời đánh dấu rõ đây là fallback.
    if current_raw is None:
        current_raw = reference_raw
        current_source = "reference_fallback"

    current = convert_price_to_vnd(
        current_raw
    )

    status = "normal"

    if flags == "*":
        status = "has_event"
    elif flags == "**":
        status = "warning_or_suspended"

    return {
        "product_id": (
            f"{SOURCE_ID}_{symbol.lower()}"
        ),
        "asset_type": "Chứng khoán",
        "symbol": symbol,
        "product_name": (
            product_name or symbol
        ),
        "exchange": (
            "HOSE"
            if exchange == "HSX"
            else exchange
        ),
        "unit": "Cổ phiếu",

        # Giá đã quy đổi sang VND/cổ phiếu.
        "current": current,

        # Giữ lại để tương thích dữ liệu cũ.
        "price": current,

        # Giá gốc hiển thị trên bảng Vietstock.
        "current_raw": decimal_to_number(
            current_raw
        ),
        "current_raw_unit": (
            "1000 VND/cổ phiếu"
        ),
        "current_source": current_source,
        "price_multiplier": (
            PRICE_MULTIPLIER
        ),

        "reference": convert_price_to_vnd(
            reference_raw
        ),
        "ceiling": convert_price_to_vnd(
            ceiling_raw
        ),
        "floor": convert_price_to_vnd(
            floor_raw
        ),
        "change": convert_price_to_vnd(
            change_raw
        ),
        "change_percent": decimal_to_number(
            change_percent
        ),

        "currency": "VND",
        "price_unit": "VND/cổ phiếu",
        "status": status,
        "source": source_url,
    }


def parse_table_rows(
    html: str,
    exchange: str,
    source_url: str,
) -> list[dict[str, Any]]:
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    results: list[dict[str, Any]] = []

    for row in soup.select("tr"):
        cells = [
            normalize_text(
                cell.get_text(
                    " ",
                    strip=True,
                )
            )
            for cell in row.find_all(
                ["th", "td"]
            )
        ]

        if not cells:
            continue

        symbol_info = None
        symbol_cell_index = None

        for index, cell in enumerate(
            cells[:5]
        ):
            info = extract_symbol_and_name(
                cell
            )

            if info is not None:
                symbol_info = info
                symbol_cell_index = index
                break

        if (
            symbol_info is None
            or symbol_cell_index is None
        ):
            continue

        symbol, product_name, flags = (
            symbol_info
        )

        remaining = cells[
            symbol_cell_index + 1:
        ]

        # Tên doanh nghiệp đôi khi nằm ở một ô riêng.
        if (
            remaining
            and not is_price_text(
                remaining[0]
            )
        ):
            if not product_name:
                product_name = remaining[0]

            remaining = remaining[1:]

        start_index = find_first_price_triplet(
            remaining
        )

        if start_index is None:
            continue

        item = build_stock_item(
            symbol=symbol,
            product_name=product_name,
            exchange=exchange,
            flags=flags,
            quote_cells=remaining[
                start_index:
            ],
            source_url=source_url,
        )

        if item is not None:
            results.append(item)

    return results


def merge_items(
    target: dict[str, dict[str, Any]],
    items: list[dict[str, Any]],
) -> int:
    before = len(target)

    for item in items:
        symbol = item["symbol"]

        # Ưu tiên bản ghi có giá khớp thật,
        # không ghi đè bằng reference fallback.
        old = target.get(symbol)

        if old is None:
            target[symbol] = item
            continue

        if (
            old.get("current_source")
            == "reference_fallback"
            and item.get("current_source")
            == "last_match"
        ):
            target[symbol] = item
            continue

        # Cập nhật bản ghi mới nhất nếu cùng chất lượng.
        if (
            old.get("current_source")
            == item.get("current_source")
        ):
            target[symbol] = item

    return len(target) - before


SCROLL_SCRIPT = """
() => {
    const result = {
        moved: 0,
        scrollables: 0,
        windowMoved: false
    };

    const root =
        document.scrollingElement ||
        document.documentElement;

    if (root) {
        const before = root.scrollTop;
        const step = Math.max(
            window.innerHeight * 0.8,
            500
        );
        const maxTop = Math.max(
            0,
            root.scrollHeight - root.clientHeight
        );

        root.scrollTop = Math.min(
            before + step,
            maxTop
        );

        if (root.scrollTop > before + 1) {
            result.moved += 1;
            result.windowMoved = true;
        }
    }

    const elements = Array.from(
        document.querySelectorAll("*")
    );

    for (const element of elements) {
        const style = getComputedStyle(element);
        const overflowY = style.overflowY;

        if (
            !["auto", "scroll"].includes(overflowY)
        ) {
            continue;
        }

        if (
            element.clientHeight < 120 ||
            element.scrollHeight <=
                element.clientHeight + 40
        ) {
            continue;
        }

        result.scrollables += 1;

        const before = element.scrollTop;
        const step = Math.max(
            element.clientHeight * 0.75,
            300
        );
        const maxTop = Math.max(
            0,
            element.scrollHeight -
                element.clientHeight
        );

        element.scrollTop = Math.min(
            before + step,
            maxTop
        );

        if (element.scrollTop > before + 1) {
            result.moved += 1;
        }
    }

    window.dispatchEvent(
        new Event("scroll")
    );

    return result;
}
"""


RESET_SCROLL_SCRIPT = """
() => {
    const root =
        document.scrollingElement ||
        document.documentElement;

    if (root) {
        root.scrollTop = 0;
    }

    for (
        const element
        of document.querySelectorAll("*")
    ) {
        const style = getComputedStyle(element);

        if (
            ["auto", "scroll"].includes(
                style.overflowY
            )
            && element.scrollHeight >
                element.clientHeight + 40
        ) {
            element.scrollTop = 0;
        }
    }
}
"""


def collect_current_snapshot(
    page: Page,
    exchange: str,
    source_url: str,
    collected: dict[str, dict[str, Any]],
) -> int:
    html = page.content()

    items = parse_table_rows(
        html,
        exchange,
        source_url,
    )

    return merge_items(
        collected,
        items,
    )


def collect_by_scrolling(
    page: Page,
    exchange: str,
    source_url: str,
    collected: dict[str, dict[str, Any]],
) -> None:
    page.evaluate(RESET_SCROLL_SCRIPT)

    stable_rounds = 0

    for round_index in range(
        1,
        MAX_SCROLL_ROUNDS + 1,
    ):
        added = collect_current_snapshot(
            page,
            exchange,
            source_url,
            collected,
        )

        if added > 0:
            stable_rounds = 0

            print(
                f"  {exchange}: "
                f"{len(collected)} mã "
                f"(vòng {round_index})"
            )
        else:
            stable_rounds += 1

        scroll_result = page.evaluate(
            SCROLL_SCRIPT
        )

        # Wheel giúp kích hoạt listener của một số
        # thư viện virtual-scroll.
        page.mouse.wheel(
            0,
            900,
        )

        page.wait_for_timeout(
            SCROLL_WAIT_MS
        )

        if (
            stable_rounds
            >= MAX_STABLE_ROUNDS
        ):
            # Thu thêm một snapshot cuối.
            collect_current_snapshot(
                page,
                exchange,
                source_url,
                collected,
            )

            if (
                not scroll_result
                or scroll_result.get(
                    "moved",
                    0,
                ) == 0
            ):
                break

            # Dù vẫn có container cuộn, nếu quá lâu
            # không có mã mới thì dừng để tránh lặp vô hạn.
            if (
                stable_rounds
                >= MAX_STABLE_ROUNDS * 2
            ):
                break


def find_search_input(
    page: Page,
):
    selectors = [
        'input[placeholder*="Nhập mã"]',
        'input[placeholder*="nhập mã"]',
        'input[placeholder*="Mã CK"]',
        'input[placeholder*="mã CK"]',
        'input[type="search"]',
    ]

    for selector in selectors:
        locator = page.locator(selector)

        try:
            count = min(
                locator.count(),
                10,
            )
        except Exception:
            continue

        for index in range(count):
            candidate = locator.nth(index)

            try:
                if candidate.is_visible():
                    return candidate
            except Exception:
                continue

    return None


def collect_by_prefix_search(
    page: Page,
    exchange: str,
    source_url: str,
    collected: dict[str, dict[str, Any]],
) -> None:
    search_input = find_search_input(page)

    if search_input is None:
        print(
            f"  {exchange}: "
            "không tìm thấy ô Nhập mã, "
            "bỏ qua fallback tiền tố"
        )
        return

    first_chars = (
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    )
    next_chars = (
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "0123456789"
    )

    def search_prefix(
        prefix: str,
    ) -> list[dict[str, Any]]:
        try:
            search_input.fill(prefix)
        except Exception:
            search_input.click()
            page.keyboard.press(
                "Meta+A"
            )
            page.keyboard.type(prefix)

        page.wait_for_timeout(
            PREFIX_WAIT_MS
        )

        items = parse_table_rows(
            page.content(),
            exchange,
            source_url,
        )

        # Chỉ nhận mã đúng tiền tố để tránh lấy
        # các dòng cũ đang bị ẩn trong DOM.
        return [
            item
            for item in items
            if item["symbol"].startswith(
                prefix
            )
        ]

    for first in first_chars:
        items = search_prefix(first)

        merge_items(
            collected,
            items,
        )

        # Nếu đúng 30 hoặc hơn, kết quả có thể
        # tiếp tục bị giới hạn. Chia nhỏ theo ký tự thứ hai.
        if len(items) >= PAGE_BATCH_SIZE:
            for second in next_chars:
                prefix = first + second

                sub_items = search_prefix(
                    prefix
                )

                merge_items(
                    collected,
                    sub_items,
                )

        print(
            f"  {exchange}: "
            f"đã quét tiền tố {first}, "
            f"tổng {len(collected)} mã"
        )

    try:
        search_input.fill("")
        page.wait_for_timeout(
            PREFIX_WAIT_MS
        )
    except Exception:
        pass


def fetch_exchange(
    browser: Browser,
    exchange: str,
    url: str,
) -> list[dict[str, Any]]:
    page = browser.new_page(
        viewport={
            "width": 1600,
            "height": 1000,
        },
        locale="vi-VN",
        timezone_id="Asia/Ho_Chi_Minh",
        user_agent=(
            "Mozilla/5.0 "
            "(Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
    )

    try:
        print(
            f"{exchange}: đang tải {url}"
        )

        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=60_000,
        )

        try:
            page.wait_for_selector(
                "table",
                timeout=20_000,
            )
        except PlaywrightTimeoutError:
            # Vẫn tiếp tục vì website có thể dùng
            # div thay vì table trong một số thời điểm.
            pass

        page.wait_for_timeout(
            INITIAL_WAIT_MS
        )

        collected: dict[
            str,
            dict[str, Any],
        ] = {}

        # Snapshot sau khi JavaScript chạy.
        collect_current_snapshot(
            page,
            exchange,
            page.url,
            collected,
        )

        # Thu thập các hàng lazy-load/virtual-scroll.
        collect_by_scrolling(
            page,
            exchange,
            page.url,
            collected,
        )

        # Nếu vẫn chỉ quanh mức 30 mã, dùng ô tìm kiếm
        # để lần lượt quét theo tiền tố.
        if (
            ENABLE_PREFIX_FALLBACK
            and len(collected)
            <= PAGE_BATCH_SIZE * 2
        ):
            print(
                f"  {exchange}: chỉ có "
                f"{len(collected)} mã sau khi cuộn; "
                "chuyển sang quét theo tiền tố"
            )

            collect_by_prefix_search(
                page,
                exchange,
                page.url,
                collected,
            )

        if not collected:
            raise RuntimeError(
                f"Không lấy được mã nào từ "
                f"{exchange}"
            )

        return sorted(
            collected.values(),
            key=lambda item: item["symbol"],
        )

    finally:
        page.close()


def scrape_vietstock() -> None:
    all_prices: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
        )

        try:
            for exchange, url in (
                EXCHANGE_URLS.items()
            ):
                try:
                    items = fetch_exchange(
                        browser,
                        exchange,
                        url,
                    )

                    all_prices.extend(items)

                    print(
                        f"{exchange}: "
                        f"lấy được {len(items)} mã"
                    )

                except Exception as error:
                    errors.append({
                        "exchange": exchange,
                        "source": url,
                        "error": str(error),
                    })

                    print(
                        f"Lỗi {exchange}: {error}"
                    )

        finally:
            browser.close()

    # Loại trùng mã giữa các snapshot.
    by_symbol: dict[
        str,
        dict[str, Any],
    ] = {}

    for item in all_prices:
        by_symbol[item["symbol"]] = item

    prices = sorted(
        by_symbol.values(),
        key=lambda item: (
            item["exchange"],
            item["symbol"],
        ),
    )

    if MAX_STOCKS is not None:
        prices = prices[:MAX_STOCKS]

    if not prices:
        print(
            "Không lấy được dữ liệu chứng khoán."
        )
        return

    exchange_counts: dict[str, int] = {}

    for item in prices:
        exchange = item["exchange"]

        exchange_counts[exchange] = (
            exchange_counts.get(
                exchange,
                0,
            )
            + 1
        )

    now = datetime.now().astimezone()

    result = {
        "last_updated": now.isoformat(
            timespec="seconds"
        ),
        "source": (
            "https://banggia.vietstock.vn"
        ),
        "source_id": SOURCE_ID,
        "currency": "VND",
        "price_unit": "VND/cổ phiếu",
        "source_price_unit": (
            "1000 VND/cổ phiếu"
        ),
        "price_multiplier": (
            PRICE_MULTIPLIER
        ),
        "count": len(prices),
        "exchange_counts": exchange_counts,
        "prices": prices,
        "errors": errors,
    }

    script_dir = os.path.dirname(
        os.path.abspath(__file__)
    )

    output_path = os.path.join(
        script_dir,
        OUTPUT_FILE,
    )

    with open(
        output_path,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            result,
            file,
            ensure_ascii=False,
            indent=2,
        )

    print()
    print("Kết quả:")

    for exchange, count in sorted(
        exchange_counts.items()
    ):
        print(
            f"  {exchange}: {count} mã"
        )

    print(
        f"  Tổng cộng: {len(prices)} mã"
    )

    print(
        "Thành công! "
        f"Đã lưu vào {output_path}"
    )


if __name__ == "__main__":
    started_at = time.time()

    scrape_vietstock()

    elapsed = time.time() - started_at

    print(
        f"Thời gian chạy: {elapsed:.1f} giây"
    )
