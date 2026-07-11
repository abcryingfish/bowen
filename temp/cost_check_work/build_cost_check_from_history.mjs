import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const projectRoot = "C:/Users/Administrator/Desktop/python_venv";
const outputDir = path.join(projectRoot, "outputs", "cost_check");
const historyCostPath = "C:/Users/Administrator/Desktop/历史成交流水_持仓成本.txt";

function toNumber(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
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

function parseTsv(text) {
  const lines = text.split(/\r?\n/).filter((line) => line.trim() !== "");
  if (lines.length === 0) return { header: [], rows: [] };
  const header = lines[0].replace(/^\uFEFF/, "").split("\t");
  const rows = lines.slice(1).map((line) => {
    const cols = line.split("\t");
    const row = {};
    header.forEach((name, i) => {
      row[name] = cols[i] ?? "";
    });
    return row;
  });
  return { header, rows };
}

const sourceText = await fs.readFile(historyCostPath, "utf8");
const source = parseTsv(sourceText);
const sourceRows = source.rows;
const updateTime = sourceRows[0]?.["更新时间"] || "";
const startDate = sourceRows[0]?.["统计开始"] || "";
const endDate = sourceRows[0]?.["统计结束"] || "";
const safeTime = updateTime.replace(/[-:\s]/g, "").slice(0, 14) || "latest";
const outputPath = path.join(outputDir, `普通账户_卖出阈值成本核对_含官方成本_${safeTime}.xlsx`);
const previewPath = path.join(outputDir, `preview_${safeTime}.png`);
const sourcePreviewPath = path.join(outputDir, `source_preview_${safeTime}.png`);

const headers = [
  "序号",
  "股票代码",
  "当前持仓",
  "可用持仓",
  "官方成本价",
  "官方成本金额",
  "官方市值",
  "官方最新价",
  "官方持仓盈亏",
  "历史买入股数",
  "历史买入金额",
  "历史买入均价",
  "历史卖出股数",
  "历史卖出金额",
  "历史净股数",
  "历史净金额",
  "历史净均价",
  "卖出判断成本",
  "成本来源",
  "150%阈值价",
  "200%阈值价",
  "最新/成本",
  "按当前价所在档位",
  "成交笔数",
  "首笔时间",
  "末笔时间",
  "数据时间",
  "备注",
];

const rows = sourceRows.map((item, idx) => {
  const currentPosition = toNumber(item["当前持仓"]);
  const officialCost = toNumber(item["官方成本价"]);
  const latestPrice = toNumber(item["官方最新价"]);
  const historyNetCost = toNumber(item["历史净均价"]);
  const thresholdCost = historyNetCost > 0 ? historyNetCost : officialCost;
  const costSource = historyNetCost > 0 ? "历史成交净均价" : "官方持仓成本兜底";
  let tier = "成本无效";
  if (thresholdCost > 0 && latestPrice >= thresholdCost * 2) {
    tier = "达到200%：清仓";
  } else if (thresholdCost > 0 && latestPrice >= thresholdCost * 1.5) {
    tier = "达到150%：卖一半";
  } else if (thresholdCost > 0) {
    tier = "未达150%：不卖";
  }
  const note = currentPosition <= 0 ? "当前持仓为0，请核对源文件" : "";
  return [
    idx + 1,
    item["股票代码"] || "",
    currentPosition,
    toNumber(item["可用持仓"]),
    officialCost || null,
    toNumber(item["官方成本金额"]) || null,
    toNumber(item["官方市值"]) || null,
    latestPrice || null,
    toNumber(item["官方持仓盈亏"]),
    toNumber(item["历史买入股数"]),
    toNumber(item["历史买入金额"]) || null,
    toNumber(item["历史买入均价"]) || null,
    toNumber(item["历史卖出股数"]),
    toNumber(item["历史卖出金额"]) || null,
    toNumber(item["历史净股数"]),
    toNumber(item["历史净金额"]) || null,
    historyNetCost || null,
    thresholdCost || null,
    costSource,
    thresholdCost > 0 ? thresholdCost * 1.5 : null,
    thresholdCost > 0 ? thresholdCost * 2 : null,
    thresholdCost > 0 && latestPrice > 0 ? latestPrice / thresholdCost : null,
    tier,
    toNumber(item["成交笔数"]),
    item["首笔时间"] || "",
    item["末笔时间"] || "",
    item["更新时间"] || "",
    note,
  ];
});

await fs.mkdir(outputDir, { recursive: true });

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("卖出成本核对");
sheet.showGridLines = false;

const lastCol = columnName(headers.length - 1);
const usedRows = Math.max(rows.length + 4, 5);

sheet.getRange(`A1:${lastCol}1`).merge();
sheet.getRange("A1").values = [["普通账户卖出阈值成本核对（含官方成本）"]];
sheet.getRange(`A2:${lastCol}2`).merge();
sheet.getRange("A2").values = [[`来源：${historyCostPath}；更新时间：${updateTime || "未识别"}；统计区间：${startDate || "-"} 至 ${endDate || "-"}；明细行数：${rows.length}。卖出判断成本口径：历史净均价 > 0 则使用历史净均价，否则使用官方持仓成本兜底。`]];
sheet.getRange(`A4:${lastCol}4`).values = [headers];
if (rows.length > 0) {
  sheet.getRange(rangeAddress(4, 0, rows.length, headers.length)).values = rows;
}

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
sheet.getRange(`E5:H${usedRows}`).format.numberFormat = "0.0000";
sheet.getRange(`F5:G${usedRows}`).format.numberFormat = "#,##0.00";
sheet.getRange(`I5:I${usedRows}`).format.numberFormat = "#,##0.00";
sheet.getRange(`J5:J${usedRows}`).format.numberFormat = "#,##0";
sheet.getRange(`K5:K${usedRows}`).format.numberFormat = "#,##0.00";
sheet.getRange(`L5:L${usedRows}`).format.numberFormat = "0.0000";
sheet.getRange(`M5:M${usedRows}`).format.numberFormat = "#,##0";
sheet.getRange(`N5:N${usedRows}`).format.numberFormat = "#,##0.00";
sheet.getRange(`O5:O${usedRows}`).format.numberFormat = "#,##0";
sheet.getRange(`P5:P${usedRows}`).format.numberFormat = "#,##0.00";
sheet.getRange(`Q5:R${usedRows}`).format.numberFormat = "0.0000";
sheet.getRange(`T5:U${usedRows}`).format.numberFormat = "0.0000";
sheet.getRange(`V5:V${usedRows}`).format.numberFormat = "0.00x";
sheet.getRange(`X5:X${usedRows}`).format.numberFormat = "#,##0";
sheet.getRange(`A:${lastCol}`).format.autofitColumns();
sheet.getRange(`A2:${lastCol}2`).format.rowHeight = 42;
sheet.getRange("B:B").format.columnWidth = 14;
sheet.getRange("S:S").format.columnWidth = 16;
sheet.getRange("W:W").format.columnWidth = 18;
sheet.getRange("AB:AB").format.columnWidth = 28;
sheet.getRange(`AB5:AB${usedRows}`).format.wrapText = true;

if (rows.length > 0) {
  const table = sheet.tables.add(`A4:${lastCol}${usedRows}`, true, "SellCostCheckTable");
  table.style = "TableStyleMedium2";
}

const raw = workbook.worksheets.add("源数据说明");
raw.showGridLines = false;
raw.getRange("A1:B8").values = [
  ["项目", "值"],
  ["成本来源文件", historyCostPath],
  ["更新时间", updateTime],
  ["统计开始", startDate],
  ["统计结束", endDate],
  ["导出行数", rows.length],
  ["判断规则", "历史净均价 > 0 则用历史净均价；否则用官方持仓成本价。"],
  ["注意", "本表只核对卖出阈值成本口径，实际卖出仍取决于交易脚本中的卖出信号与账户可交易状态。"],
];
raw.getRange("A1:B1").format = { fill: "#1F4E79", font: { bold: true, color: "#FFFFFF" } };
raw.getRange("A:B").format.autofitColumns();
raw.getRange("B:B").format.columnWidth = 100;
raw.getRange("B:B").format.wrapText = true;

const inspect = await workbook.inspect({
  kind: "table",
  range: `卖出成本核对!A4:${lastCol}${Math.min(usedRows, 12)}`,
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

const preview = await workbook.render({ sheetName: "卖出成本核对", range: `A1:${lastCol}18`, scale: 1, format: "png" });
await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
const sourcePreview = await workbook.render({ sheetName: "源数据说明", range: "A1:B8", scale: 1, format: "png" });
await fs.writeFile(sourcePreviewPath, new Uint8Array(await sourcePreview.arrayBuffer()));

const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outputPath);
console.log(`OUTPUT=${outputPath}`);
console.log(`PREVIEW=${previewPath}`);
console.log(`SOURCE_PREVIEW=${sourcePreviewPath}`);
