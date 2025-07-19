const https = require("https");
const fs = require("fs");
const path = require("path");

const dir = path.join(__dirname, "coins");
if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });

const allCoinsUrl = "https://api.coingecko.com/api/v3/coins/list";
const top200CoinsUrl = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=200&page=1";

function fetchJson(url) {
  return new Promise((resolve, reject) => {
    https.get(url, (res) => {
      let data = "";
      res.on("data", chunk => data += chunk);
      res.on("end", () => {
        try {
          const json = JSON.parse(data);
          resolve(json);
        } catch (err) {
          reject(new Error("Lỗi khi phân tích JSON: " + err.message));
        }
      });
    }).on("error", err => {
      reject(new Error("Lỗi kết nối API: " + err.message));
    });
  });
}

function simplifyTopCoins(topCoins) {
  return topCoins.map(c => ({
    id: c.id,
    symbol: c.symbol,
    name: c.name,
  }));
}

async function main() {
  try {
    // Lấy danh sách tất cả coin
    const allCoins = await fetchJson(allCoinsUrl);
    fs.writeFileSync(path.join(dir, "all_coins.json"), JSON.stringify(allCoins, null, 2));
    console.log(`✅ Đã lưu ${allCoins.length} coin vào coins/all_coins.json`);

    // Lấy danh sách 200 coin phổ biến theo vốn hóa
    const top200Coins = await fetchJson(top200CoinsUrl);
    const simplifiedTop200 = simplifyTopCoins(top200Coins);
    fs.writeFileSync(path.join(dir, "top_200_coins_simple.json"), JSON.stringify(simplifiedTop200, null, 2));
    console.log(`✅ Đã lưu ${simplifiedTop200.length} coin phổ biến vào coins/top_200_coins_simple.json`);
  } catch (err) {
    console.error("❌ Lỗi:", err.message);
    process.exit(1);
  }
}

main();
