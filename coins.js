const https = require("https");
const fs = require("fs");
const path = require("path");

const dir = path.join(__dirname, "coins");
if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });

const allCoinsUrl = "https://api.coingecko.com/api/v3/coins/list";
const top200CoinsUrl = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=200&page=1";

function fetchJson(url) {
  return new Promise((resolve, reject) => {
    https.get(url, { headers: { "User-Agent": "Mozilla/5.0" } }, (res) => {
      let data = "";

      console.log(`GET ${url}`);
      console.log(`Status Code: ${res.statusCode}`);
      console.log("Headers:", res.headers);

      res.on("data", chunk => data += chunk);
      res.on("end", () => {
        console.log("Response data (first 1000 chars):");
        console.log(data.slice(0, 1000));

        if (res.statusCode !== 200) {
          reject(new Error(`HTTP error ${res.statusCode}`));
          return;
        }

        try {
          const json = JSON.parse(data);
          resolve(json);
        } catch (err) {
          console.error("❌ Lỗi khi phân tích JSON:", err.message);
          reject(err);
        }
      });
    }).on("error", err => {
      console.error("❌ Lỗi kết nối API:", err.message);
      reject(err);
    });
  });
}

function simplifyCoins(coins) {
  return coins.map(c => ({
    id: c.id,
    symbol: c.symbol,
    name: c.name,
    current_price: c.current_price || null,
    market_cap: c.market_cap || null,
    market_cap_rank: c.market_cap_rank || null,
  }));
}

async function main() {
  try {
    // Lấy danh sách tất cả coin
    const allCoins = await fetchJson(allCoinsUrl);
    console.log(`✅ Lấy được ${allCoins.length} coin tổng`);
    const allCoinsPath = path.join(dir, "all_coins.json");
    fs.writeFileSync(allCoinsPath, JSON.stringify(allCoins, null, 2));
    console.log(`✅ Đã lưu danh sách tất cả coin vào ${allCoinsPath}`);

    // Lấy danh sách 200 coin phổ biến
    const top200Coins = await fetchJson(top200CoinsUrl);
    console.log(`✅ Lấy được ${top200Coins.length} coin phổ biến`);
    const simplifiedTop200 = simplifyCoins(top200Coins);
    const top200Path = path.join(dir, "top_200_coins_simple.json");
    fs.writeFileSync(top200Path, JSON.stringify(simplifiedTop200, null, 2));
    console.log(`✅ Đã lưu danh sách 200 coin phổ biến vào ${top200Path}`);
  } catch (err) {
    console.error("❌ Lỗi khi lấy hoặc lưu dữ liệu:", err.message);
    process.exit(1);
  }
}

main();
