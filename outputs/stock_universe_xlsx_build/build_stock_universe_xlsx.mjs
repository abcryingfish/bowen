import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const inputJson = path.join(__dirname, "stock_universe_rows.json");
const outputDir = path.resolve(__dirname, "..");
const outputPath = path.join(outputDir, "全市场股票代码.xlsx");

const rows = JSON.parse(await fs.readFile(inputJson, "utf8"));
const workbook = Workbook.create();
const sheet = workbook.worksheets.add("全市场股票代码");
sheet.showGridLines = false;

const headers = ["股票代码", "股票名称", "上市状态", "交易所", "拼音首字母"];
const data = rows.map((row) => [
  row.htsc_code ?? "",
  row.name ?? "",
  row.listing_state ?? "",
  row.exchange ?? "",
  row.pinyin_initials ?? "",
]);

sheet.getRange("A1:E1").values = [headers];
if (data.length) {
  sheet.getRangeByIndexes(1, 0, data.length, headers.length).values = data;
}

const usedRange = sheet.getRangeByIndexes(0, 0, data.length + 1, headers.length);
usedRange.format = {
  font: { name: "Microsoft YaHei", size: 10, color: "#1F2937" },
  borders: { preset: "all", style: "thin", color: "#E5E7EB" },
};

const headerRange = sheet.getRange("A1:E1");
headerRange.format = {
  fill: "#1F4E79",
  font: { name: "Microsoft YaHei", bold: true, color: "#FFFFFF", size: 10 },
  borders: { preset: "all", style: "thin", color: "#1F4E79" },
};

sheet.freezePanes.freezeRows(1);
sheet.getRange("A:A").format.columnWidthPx = 110;
sheet.getRange("B:B").format.columnWidthPx = 150;
sheet.getRange("C:C").format.columnWidthPx = 110;
sheet.getRange("D:D").format.columnWidthPx = 85;
sheet.getRange("E:E").format.columnWidthPx = 120;

const tableRange = `A1:E${data.length + 1}`;
const table = sheet.tables.add(tableRange, true, "StockUniverseTable");
table.style = "TableStyleMedium2";
table.showFilterButton = true;

const meta = workbook.worksheets.add("说明");
meta.showGridLines = false;
meta.getRange("A1:B5").values = [
  ["项目", "内容"],
  ["来源文件", "全市场股票代码/universe.parquet"],
  ["记录数", data.length],
  ["导出时间", new Date().toLocaleString("zh-CN", { hour12: false })],
  ["备注", "股票代码、名称、上市状态、交易所、拼音首字母来自本地股票池。"],
];
meta.getRange("A1:B1").format = {
  fill: "#1F4E79",
  font: { name: "Microsoft YaHei", bold: true, color: "#FFFFFF", size: 10 },
};
meta.getRange("A1:B5").format = {
  font: { name: "Microsoft YaHei", size: 10, color: "#1F2937" },
  borders: { preset: "all", style: "thin", color: "#E5E7EB" },
};
meta.getRange("A:A").format.columnWidthPx = 110;
meta.getRange("B:B").format.columnWidthPx = 420;

const sample = await workbook.inspect({
  kind: "table",
  range: "全市场股票代码!A1:E8",
  include: "values",
  tableMaxRows: 8,
  tableMaxCols: 5,
  maxChars: 3000,
});
console.log(sample.ndjson);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 20 },
  summary: "formula error scan",
});
console.log(errors.ndjson);

const preview = await workbook.render({
  sheetName: "全市场股票代码",
  range: "A1:E20",
  scale: 1,
  format: "png",
});
await fs.writeFile(path.join(outputDir, "全市场股票代码_preview.png"), new Uint8Array(await preview.arrayBuffer()));

await fs.mkdir(outputDir, { recursive: true });
const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outputPath);
console.log(JSON.stringify({ outputPath, rows: data.length }, null, 2));
