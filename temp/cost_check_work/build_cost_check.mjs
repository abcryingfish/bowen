import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const projectRoot = "C:/Users/Administrator/Desktop/python_venv";
const outputDir = path.join(projectRoot, "outputs", "cost_check");
const logPath = path.join(projectRoot, "trade_record_log.txt");
const historyCostPath = "C:/Users/Administrator/Desktop/\u5386\u53f2\u6210\u4ea4\u6d41\u6c34_\u6301\u4ed3\u6210\u672c.txt";
const outputPath = path.join(outputDir, "\u666e\u901a\u8d26\u6237_\u5356\u51fa\u9608\u503c\u6210\u672c\u6838\u5bf9_\u542b\u5b98\u65b9\u6210\u672c.xlsx");
const previewPath = path.join(outputDir, "preview.png");
const sourcePreviewPath = path.join(outputDir, "source_preview.png");

const titleCurrentPosition = "\u5f53\u524d\u6301\u4ed3\u660e\u7ec6";
const headerHistory = [
  "\u66f4\u65b0\u65f6\u95f4",
  "\u7edf\u8ba1\u5f00\u59cb",
  "\u7edf\u8ba1\u7ed3\u675f",
  "\u80a1\u7968\u4ee3\u7801",
  "\u5f53\u524d\u6301\u4ed3",
  "\u53ef\u7528\u6301\u4ed3",
  "\u5b98\u65b9\u6210\u672c\u4ef7",
  "\u5b98\u65b9\u6210\u672c\u91d1\u989d",
  "\u5b98\u65b9\u5e02\u503c",
  "\u5b98\u65b9\u6700\u65b0\u4ef7",
  "\u5b98\u65b9\u6301\u4ed3\u76c8\u4e8f",
  "\u5386\u53f2\u4e70\u5165\u80a1\u6570",
  "\u5386\u53f2\u4e70\u5165\u91d1\u989d",
  "\u5386\u53f2\u4e70\u5165\u5747\u4ef7",
  "\u5386\u53f2\u5356\u51fa\u80a1\u6570",
  "\u5386\u53f2\u5356\u51fa\u91d1\u989d",
  "\u5386\u53f2\u51c0\u80a1\u6570",
  "\u5386\u53f2\u51c0\u91d1\u989d",
  "\u5386\u53f2\u51c0\u5747\u4ef7",
  "\u6210\u4ea4\u7b14\u6570",
  "\u9996\u7b14\u65f6\u95f4",
  "\u672b\u7b14\u65f6\u95f4",
];

function toNumber(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function parseLatestPositions(logText) {
  const escapedTitle = titleCurrentPosition.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const re = new RegExp("^\\[(?<ts>[^\\]]+)\\] " + escapedTitle + "\\r?\\n(?<json>\\{.*?\\})\\s*$", "gm");
  const items = [];
  for (const match of logText.matchAll(re)) {
    try {
      items.push({ timestamp: match.groups.ts, data: JSON.parse(match.groups.json) });
    } catch {
      // Ignore malformed historical log fragments.
    }
  }
  if (items.length === 0) return { timestamp: "", rows: [] };
  const latestTimestamp = items[items.length - 1].timestamp;
  return {
    timestamp: latestTimestamp,
    rows: items.filter((item) => item.timestamp === latestTimestamp).map((item) => item.data),
  };
}

async function parseHistoryCosts() {
  let text = "";
  try {
    text = await fs.readFile(historyCostPath, "utf8");
  } catch {
    return { updateTime: "", rows: new Map(), rowCount: 0 };
  }
  const lines = text.split(/\r?\n/).filter((line) => line.trim() !== "");
  if (lines.length <= 1) return { updateTime: "", rows: new Map(), rowCount: 0 };
  const header = lines[0].split("\t");
  const index = Object.fromEntries(header.map((name, i) => [name, i]));
  const rows = new Map();
  for (const line of lines.slice(1)) {
    const cols = line.split("\t");
    const code = cols[index["\u80a1\u7968\u4ee3\u7801"]] || "";
    if (!code) continue;
    rows.set(code, {
      updateTime: cols[index["\u66f4\u65b0\u65f6\u95f4"]] || "",
      historyNetCost: toNumber(cols[index["\u5386\u53f2\u51c0\u5747\u4ef7"]]),
      historyBuyCost: toNumber(cols[index["\u5386\u53f2\u4e70\u5165\u5747\u4ef7"]]),
      dealCount: toNumber(cols[index["\u6210\u4ea4\u7b14\u6570"]]),
    });
  }
  return {
    updateTime: rows.size > 0 ? Array.from(rows.values())[0].updateTime : "",
    rows,
    rowCount: rows.size,
  };
}

function columnName(index) {
  let name = "";
  let n = index + 1;
  while (n > 0) {
    const rem = (n - 1) % 26;
    name = String.fromCharCode(65 + rem) + name;
    n = Math.floor((n - 1) / 26);
  }
  return name;
}

function rangeAddress(startRow, startCol, rowCount, colCount) {
  const start = `${columnName(startCol)}${startRow + 1}`;
  const end = `${columnName(startCol + colCount - 1)}${startRow + rowCount}`;
  return `${start}:${end}`;
}

const logText = await fs.readFile(logPath, "utf8");
const latest = parseLatestPositions(logText);
const history = await parseHistoryCosts();

const headers = [
  "\u5e8f\u53f7",
  "\u80a1\u7968\u4ee3\u7801",
  "\u603b\u6301\u4ed3",
  "\u53ef\u7528\u6301\u4ed3",
  "\u5b98\u65b9\u6210\u672c\u4ef7(\u65e5\u5fd7)",
  "\u5b98\u65b9\u6210\u672c\u91d1\u989d(\u6210\u672c\u4ef7*\u6301\u4ed3)",
  "\u5b98\u65b9\u6210\u672c\u91d1\u989d(\u5e02\u503c-\u76c8\u4e8f)",
  "\u5b98\u65b9\u53cd\u63a8\u6210\u672c\u4ef7",
  "\u5b98\u65b9\u4e24\u79cd\u6210\u672c\u4ef7\u5dee\u5f02",
  "\u5386\u53f2\u51c0\u5747\u4ef7",
  "\u5386\u53f2\u4e70\u5165\u5747\u4ef7",
  "\u5356\u51fa\u5224\u65ad\u6210\u672c",
  "\u6210\u672c\u6765\u6e90",
  "150%\u9608\u503c\u4ef7",
  "200%\u9608\u503c\u4ef7",
  "\u6700\u65b0\u4ef7",
  "\u6700\u65b0/\u6210\u672c",
  "\u6309\u5f53\u524d\u4ef7\u6240\u5728\u6863\u4f4d",
  "\u5e02\u503c",
  "\u6d6e\u52a8\u76c8\u4e8f",
  "\u5386\u53f2\u6210\u4ea4\u7b14\u6570",
  "\u6570\u636e\u65f6\u95f4",
  "\u5907\u6ce8",
];

const rows = latest.rows.map((item, idx) => {
  const code = String(item["\u80a1\u7968\u4ee3\u7801"] || "");
  const volume = toNumber(item["\u603b\u6301\u4ed3"]);
  const canUseVolume = toNumber(item["\u53ef\u7528\u6301\u4ed3"]);
  const officialCost = toNumber(item["\u6210\u672c\u4ef7"]);
  const marketValue = toNumber(item["\u5e02\u503c"]);
  const profit = toNumber(item["\u6d6e\u52a8\u76c8\u4e8f"]);
  const officialCostAmountByPrice = officialCost && volume ? officialCost * volume : null;
  const officialCostAmountByProfit = marketValue - profit;
  const officialCostByProfit = volume > 0 ? officialCostAmountByProfit / volume : null;
  const officialCostDiff = officialCostByProfit !== null ? officialCost - officialCostByProfit : null;
  const hist = history.rows.get(code);
  const historyNetCost = hist ? hist.historyNetCost : 0;
  const historyBuyCost = hist ? hist.historyBuyCost : 0;
  const thresholdCost = historyNetCost > 0 ? historyNetCost : officialCost;
  const latestPrice = toNumber(item["\u6700\u65b0\u4ef7"]);
  let source = historyNetCost > 0 ? "\u5386\u53f2\u6210\u4ea4\u51c0\u5747\u4ef7" : "\u5b98\u65b9\u6301\u4ed3\u6210\u672c\u515c\u5e95";
  let tier = "\u6210\u672c\u65e0\u6548";
  if (thresholdCost > 0 && latestPrice >= thresholdCost * 2) {
    tier = "\u8fbe\u5230200%\uff1a\u6e05\u4ed3";
  } else if (thresholdCost > 0 && latestPrice >= thresholdCost * 1.5) {
    tier = "\u8fbe\u5230150%\uff1a\u5356\u4e00\u534a";
  } else if (thresholdCost > 0) {
    tier = "\u672a\u8fbe150%\uff1a\u4e0d\u5356";
  }
  const note = history.rowCount === 0
    ? "\u5386\u53f2\u6210\u4ea4\u6210\u672c\u6587\u4ef6\u65e0\u660e\u7ec6\uff0c\u672c\u6b21\u5168\u90e8\u7528\u5b98\u65b9\u6210\u672c\u515c\u5e95"
    : "";
  return [
    idx + 1,
    code,
    volume,
    canUseVolume,
    officialCost,
    officialCostAmountByPrice,
    officialCostAmountByProfit,
    officialCostByProfit,
    officialCostDiff,
    historyNetCost || null,
    historyBuyCost || null,
    thresholdCost || null,
    source,
    thresholdCost > 0 ? thresholdCost * 1.5 : null,
    thresholdCost > 0 ? thresholdCost * 2 : null,
    latestPrice || null,
    thresholdCost > 0 && latestPrice > 0 ? latestPrice / thresholdCost : null,
    tier,
    marketValue,
    profit,
    hist ? hist.dealCount : 0,
    latest.timestamp,
    note,
  ];
});

await fs.mkdir(outputDir, { recursive: true });

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("\u5356\u51fa\u6210\u672c\u6838\u5bf9");
sheet.showGridLines = false;

const lastCol = columnName(headers.length - 1);
sheet.getRange(`A1:${lastCol}1`).merge();
sheet.getRange("A1").values = [["\u666e\u901a\u8d26\u6237\u5356\u51fa\u9608\u503c\u6210\u672c\u6838\u5bf9"]];
sheet.getRange(`A2:${lastCol}2`).merge();
sheet.getRange("A2").values = [[`\u53e3\u5f84\uff1a\u4ee3\u7801\u5356\u51fa\u5224\u65ad\u4f7f\u7528\u5386\u53f2\u51c0\u5747\u4ef7\uff1b\u82e5\u5386\u53f2\u6210\u672c<=0\uff0c\u5219\u4f7f\u7528\u5b98\u65b9\u6301\u4ed3\u6210\u672c\u515c\u5e95\u3002\u672c\u8868\u540c\u65f6\u5217\u51fa\u65e5\u5fd7\u76f4\u51fa\u5b98\u65b9\u6210\u672c\u4ef7\u3001\u6210\u672c\u4ef7*\u6301\u4ed3\u3001\u5e02\u503c-\u76c8\u4e8f\u53cd\u63a8\u6210\u672c\u3002\u6700\u65b0\u6301\u4ed3\u65f6\u95f4\uff1a${latest.timestamp || "\u672a\u627e\u5230"}\uff1b\u5386\u53f2\u6210\u672c\u660e\u7ec6\u884c\u6570\uff1a${history.rowCount}`]];
sheet.getRange(`A4:${lastCol}4`).values = [headers];
if (rows.length > 0) {
  sheet.getRange(rangeAddress(4, 0, rows.length, headers.length)).values = rows;
}

const usedRows = Math.max(rows.length + 4, 5);
sheet.freezePanes.freezeRows(4);
sheet.getRange(`A1:${lastCol}1`).format = {
  fill: "#1F4E79",
  font: { bold: true, color: "#FFFFFF", size: 14 },
  horizontalAlignment: "center",
};
sheet.getRange(`A2:${lastCol}2`).format = {
  fill: "#EAF2F8",
  font: { color: "#1F2937" },
  wrapText: true,
};
sheet.getRange(`A4:${lastCol}4`).format = {
  fill: "#5B9BD5",
  font: { bold: true, color: "#FFFFFF" },
  borders: { preset: "outside", style: "thin", color: "#9EADBD" },
  wrapText: true,
};
sheet.getRange(`A4:${lastCol}${usedRows}`).format.borders = { preset: "inside", style: "thin", color: "#D9E2F3" };
sheet.getRange(`A5:A${usedRows}`).format.numberFormat = "#,##0";
sheet.getRange(`C5:D${usedRows}`).format.numberFormat = "#,##0";
sheet.getRange(`E5:E${usedRows}`).format.numberFormat = "0.0000";
sheet.getRange(`F5:G${usedRows}`).format.numberFormat = "#,##0.00";
sheet.getRange(`H5:L${usedRows}`).format.numberFormat = "0.0000";
sheet.getRange(`N5:P${usedRows}`).format.numberFormat = "0.0000";
sheet.getRange(`Q5:Q${usedRows}`).format.numberFormat = "0.00x";
sheet.getRange(`S5:T${usedRows}`).format.numberFormat = "#,##0.00";
sheet.getRange(`U5:U${usedRows}`).format.numberFormat = "#,##0";
sheet.getRange(`A:${lastCol}`).format.autofitColumns();
sheet.getRange(`A2:${lastCol}2`).format.rowHeight = 42;
sheet.getRange("B:B").format.columnWidth = 14;
sheet.getRange("R:R").format.columnWidth = 18;
sheet.getRange("W:W").format.columnWidth = 34;
sheet.getRange(`W5:W${usedRows}`).format.wrapText = true;

if (rows.length > 0) {
  const table = sheet.tables.add(`A4:${lastCol}${usedRows}`, true, "SellCostCheckTable");
  table.style = "TableStyleMedium2";
}

const raw = workbook.worksheets.add("\u6e90\u6570\u636e\u8bf4\u660e");
raw.showGridLines = false;
raw.getRange("A1:B10").values = [
  ["\u9879\u76ee", "\u503c"],
  ["\u6301\u4ed3\u6765\u6e90", logPath],
  ["\u5386\u53f2\u6210\u672c\u6765\u6e90", historyCostPath],
  ["\u6700\u65b0\u6301\u4ed3\u65f6\u95f4", latest.timestamp || ""],
  ["\u6301\u4ed3\u660e\u7ec6\u884c\u6570", rows.length],
  ["\u5386\u53f2\u6210\u672c\u660e\u7ec6\u884c\u6570", history.rowCount],
  ["\u4ee3\u7801\u5224\u65ad\u987a\u5e8f", "\u5386\u53f2\u51c0\u5747\u4ef7 > 0 \u5219\u7528\u5386\u53f2\u51c0\u5747\u4ef7\uff1b\u5426\u5219\u7528\u5b98\u65b9\u6210\u672c\u4ef7"],
  ["\u4ee3\u7801\u4e2d\u517c\u5bb9\u7684\u5b98\u65b9\u6210\u672c\u4ef7\u5b57\u6bb5", "avg_price / open_price / costPrice / cost_price / m_dOpenPrice / m_dCostPrice / m_dPositionCostPrice"],
  ["\u4ee3\u7801\u4e2d\u517c\u5bb9\u7684\u5b98\u65b9\u6210\u672c\u91d1\u989d\u5b57\u6bb5", "costBalance / cost_balance / position_cost / positionCost / m_dPositionCost / m_dCostBalance / m_dOpenCost"],
  ["\u6ce8\u610f", "\u5b9e\u9645\u5356\u51fa\u4ecd\u9700\u8981\u5f31\u5356\u4fe1\u53f7\u89e6\u53d1\uff1bExcel\u53ea\u6838\u5bf9\u4ef7\u683c\u9608\u503c\u6210\u672c\u3002\u5f53\u524d\u6301\u4ed3\u660e\u7ec6\u65e5\u5fd7\u53ea\u76f4\u63a5\u8bb0\u5f55\u4e86\u5b98\u65b9\u6210\u672c\u4ef7\uff0c\u5176\u4ed6\u5b98\u65b9\u6210\u672c\u53e3\u5f84\u7531\u5e02\u503c/\u76c8\u4e8f\u53cd\u63a8\u6216\u4ee3\u7801\u5b57\u6bb5\u8868\u8fbe"],
];
raw.getRange("A1:B1").format = { fill: "#1F4E79", font: { bold: true, color: "#FFFFFF" } };
raw.getRange("A:B").format.autofitColumns();
raw.getRange("B:B").format.columnWidth = 100;
raw.getRange("B:B").format.wrapText = true;

const inspect = await workbook.inspect({
  kind: "table",
  range: `\u5356\u51fa\u6210\u672c\u6838\u5bf9!A4:${lastCol}${Math.min(usedRows, 12)}`,
  include: "values",
  tableMaxRows: 12,
  tableMaxCols: headers.length,
  maxChars: 6000,
});
console.log(inspect.ndjson);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "formula error scan",
});
console.log(errors.ndjson);

const preview = await workbook.render({ sheetName: "\u5356\u51fa\u6210\u672c\u6838\u5bf9", range: `A1:${lastCol}16`, scale: 1, format: "png" });
await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
const sourcePreview = await workbook.render({ sheetName: "\u6e90\u6570\u636e\u8bf4\u660e", range: "A1:B10", scale: 1, format: "png" });
await fs.writeFile(sourcePreviewPath, new Uint8Array(await sourcePreview.arrayBuffer()));

const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outputPath);
console.log(`OUTPUT=${outputPath}`);
console.log(`PREVIEW=${previewPath}`);
console.log(`SOURCE_PREVIEW=${sourcePreviewPath}`);
