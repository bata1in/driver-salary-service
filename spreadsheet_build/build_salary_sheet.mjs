import fs from "node:fs/promises";
import { execFileSync } from "node:child_process";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const sourcePath = "/Users/antonbatalin/Downloads/Маршруты 1-15 мая.xlsx";
const outputDir = "/Users/antonbatalin/Documents/Подсчет зп водителей/outputs/salary_may_1_15";
const outputPath = `${outputDir}/Расчет_ЗП_водителей_1-15_мая_2026.xlsx`;
const pythonBin = "/Users/antonbatalin/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3";

const py = String.raw`
import json
import re
from collections import defaultdict
from datetime import datetime, date, time
from openpyxl import load_workbook

source_path = r"/Users/antonbatalin/Downloads/Маршруты 1-15 мая.xlsx"
wb = load_workbook(source_path, data_only=True, read_only=True)
ws = wb.active
rows = [list(row) for row in ws.iter_rows(values_only=True)]

route_re = re.compile(r"Маршрутный лист\s+([\d\s\xa0]+)\s+от\s+(\d{2}\.\d{2}\.\d{4})")
route_starts = []
for idx, row in enumerate(rows):
    value = row[0] if row else None
    if isinstance(value, str) and value.startswith("Маршрутный лист ") and " от " in value:
        route_starts.append(idx)
route_starts.append(len(rows))

def clean_text(value):
    if value is None:
        return ""
    return " ".join(str(value).replace("\xa0", " ").split()).strip()

def normalize_address(value):
    return clean_text(value).lower()

def parse_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        value = clean_text(value)
        for fmt in ("%d.%m.%Y", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                pass
    return None

def parse_datetime(value, base_date):
    if isinstance(value, datetime):
        return value
    if isinstance(value, time):
        return datetime.combine(base_date, value)
    if isinstance(value, (int, float)) and 0 <= value < 1 and base_date:
        total_seconds = round(value * 86400)
        return datetime.combine(base_date, time(total_seconds // 3600 % 24, total_seconds // 60 % 60, total_seconds % 60))
    if isinstance(value, str):
        value = clean_text(value)
        for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                pass
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                return datetime.combine(base_date, datetime.strptime(value, fmt).time())
            except ValueError:
                pass
    return None

def best_delivery_time(row, delivery_date):
    # Prefer actual visit/departure timestamps. Some delivery marks are posted next morning,
    # which would otherwise create false overtime.
    for idx in (25, 24):  # Z: visit, Y: departure
        value = row[idx] if len(row) > idx else None
        dt = parse_datetime(value, delivery_date)
        if dt:
            return dt
    mark = row[26] if len(row) > 26 else None  # AA: delivery mark
    dt = parse_datetime(mark, delivery_date)
    if dt and dt.date() == delivery_date:
        return dt
    return None

def parse_number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        value = value.replace("\xa0", "").replace(" ", "").replace(",", ".")
        try:
            return float(value)
        except ValueError:
            return None
    return None

def excel_value(value):
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%d.%m.%Y")
    if isinstance(value, time):
        return value.strftime("%H:%M:%S")
    if value is None:
        return None
    return value

max_cols = max(len(row) for row in rows)
source_rows = []
for row in rows:
    padded = list(row) + [None] * (max_cols - len(row))
    source_rows.append([excel_value(value) for value in padded])

daily = {}
detail_rows = []
for route_idx, start in enumerate(route_starts[:-1]):
    end = route_starts[route_idx + 1]
    header = rows[start]
    match = route_re.search(str(header[0]))
    if not match:
        continue
    route_no = clean_text(match.group(1))
    route_weight = parse_number(header[27] if len(header) > 27 else None)
    groups = defaultdict(list)
    for row_index, row in enumerate(rows[start + 1:end], start=start + 2):
        delivery_date = parse_date(row[0] if row else None)
        courier = clean_text(row[18] if len(row) > 18 else None)
        if delivery_date and courier:
            groups[(delivery_date.isoformat(), courier)].append((row_index, row))
    for (date_key, driver), group in groups.items():
        delivery_date = datetime.strptime(date_key, "%Y-%m-%d").date()
        daily_key = (date_key, driver)
        entry = daily.setdefault(daily_key, {
            "date": date_key,
            "driver": driver,
            "routes": set(),
            "weight": 0.0,
            "addresses": set(),
            "request_rows": 0,
            "last_delivery": None,
        })
        entry["routes"].add(route_no)
        if len(groups) == 1 and route_weight is not None:
            entry["weight"] += route_weight
        else:
            entry["weight"] += sum(parse_number(row[27] if len(row) > 27 else None) or 0 for _, row in group)
        entry["request_rows"] += len(group)
        for row_index, row in group:
            address = normalize_address(row[10] if len(row) > 10 else None) or normalize_address(row[9] if len(row) > 9 else None)
            if address:
                entry["addresses"].add(address)
            dt = best_delivery_time(row, delivery_date)
            if dt and (entry["last_delivery"] is None or dt > entry["last_delivery"]):
                entry["last_delivery"] = dt
            detail_rows.append({
                "date": date_key,
                "driver": driver,
                "route": route_no,
                "source_row": row_index,
                "address_norm": address,
                "delivery_time": dt.isoformat(sep=" ") if dt else None,
            })

daily_rows = []
for entry in daily.values():
    daily_rows.append({
        "date": entry["date"],
        "month": entry["date"][:7],
        "driver": entry["driver"],
        "routes": ", ".join(sorted(entry["routes"])),
        "route_count": len(entry["routes"]),
        "weight": round(entry["weight"], 3),
        "address_count": len(entry["addresses"]),
        "request_rows": entry["request_rows"],
        "last_delivery": entry["last_delivery"].isoformat(sep=" ") if entry["last_delivery"] else None,
    })
daily_rows.sort(key=lambda row: (row["date"], row["driver"]))

summary_keys = sorted({(row["driver"], row["month"]) for row in daily_rows})
summary_rows = [{"driver": driver, "month": month} for driver, month in summary_keys]

print(json.dumps({
    "source_rows": source_rows,
    "daily_rows": daily_rows,
    "summary_rows": summary_rows,
}, ensure_ascii=False))
`;

const payload = JSON.parse(execFileSync(pythonBin, ["-c", py], { encoding: "utf8", maxBuffer: 20 * 1024 * 1024 }));

function colName(n) {
  let name = "";
  while (n > 0) {
    const rem = (n - 1) % 26;
    name = String.fromCharCode(65 + rem) + name;
    n = Math.floor((n - 1) / 26);
  }
  return name;
}

function ruDate(value) {
  if (!value) return null;
  const [y, m, d] = value.slice(0, 10).split("-").map(Number);
  return Math.floor((Date.UTC(y, m - 1, d) - Date.UTC(1899, 11, 30)) / 86400000);
}

function ruDateTime(value) {
  if (!value) return null;
  const [datePart, timePart = "00:00:00"] = value.split(" ");
  const [y, m, d] = datePart.split("-").map(Number);
  const [hh, mm, ss = 0] = timePart.split(":").map(Number);
  const dateSerial = Math.floor((Date.UTC(y, m - 1, d) - Date.UTC(1899, 11, 30)) / 86400000);
  return dateSerial + (hh * 3600 + mm * 60 + ss) / 86400;
}

function formatDateRu(value) {
  if (!value) return null;
  const [y, m, d] = value.slice(0, 10).split("-");
  return `${d}.${m}.${y}`;
}

function formatDateTimeRu(value) {
  if (!value) return null;
  const [datePart, timePart = "00:00:00"] = value.split(" ");
  const [y, m, d] = datePart.split("-");
  return `${d}.${m}.${y} ${timePart.slice(0, 5)}`;
}

function setHeader(range) {
  range.format = {
    fill: "#1F4E78",
    font: { color: "#FFFFFF", bold: true },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "outside", style: "thin", color: "#D9E2F3" },
  };
}

function setTableBody(range) {
  range.format = {
    borders: { preset: "all", style: "thin", color: "#E5E7EB" },
    verticalAlignment: "center",
  };
}

const workbook = Workbook.create();
const report = workbook.worksheets.add("Отчет");
const calc = workbook.worksheets.add("Расчеты");
const summary = workbook.worksheets.add("Свод");

const reportRows = payload.source_rows;
const reportCols = Math.max(...reportRows.map((row) => row.length));
const reportEnd = `${colName(reportCols)}${reportRows.length}`;
report.getRange(`A1:${reportEnd}`).values = reportRows;
report.getRange("A1:AD5").format = { fill: "#F3F6FA", font: { bold: true }, wrapText: true };
report.getRange("A5:AD5").format = { fill: "#1F4E78", font: { color: "#FFFFFF", bold: true }, wrapText: true };
report.getRange(`A1:${reportEnd}`).format.borders = { preset: "all", style: "thin", color: "#E6EAF0" };
report.getRange("A:AD").format.autofitColumns();

const ruleWeight = [
  ["Мин вес, кг", "Бонус, руб"],
  [0, 0],
  [501, 500],
  [701, 1000],
  [901, 1400],
  [1101, 1700],
  [1301, 2500],
  [1601, 3000],
];
const ruleAddress = [
  ["Мин адресов", "Бонус, руб"],
  [0, 0],
  [13, 500],
  [19, 700],
  [25, 1500],
  [31, 1800],
];

calc.getRange("A1").values = [["Расчет ЗП водителей, 1-15 мая 2026"]];
calc.getRange("A1:M1").format = { fill: "#0F172A", font: { color: "#FFFFFF", bold: true, size: 14 }, horizontalAlignment: "left" };
calc.getRange("A3:M3").values = [[
  "Дата", "Месяц", "Водитель", "Маршрутные листы", "Маршрутов", "Вес за день, кг",
  "Уникальных адресов", "Заявок в отчете", "Последняя доставка", "Бонус вес",
  "Бонус адреса", "Переработка, мин", "Итого бонус",
]];
setHeader(calc.getRange("A3:M3"));

const dailyRows = payload.daily_rows.map((row) => [
  formatDateRu(row.date),
  row.month,
  row.driver,
  row.routes,
  row.route_count,
  row.weight,
  row.address_count,
  row.request_rows,
  formatDateTimeRu(row.last_delivery),
  null,
  null,
  null,
  null,
]);
calc.getRange("A4").values = dailyRows;
const lastCalcRow = 3 + dailyRows.length;
calc.getRange("V3:W3").values = [["Служ. дата", "Служ. доставка"]];
calc.getRange("V4").values = payload.daily_rows.map((row) => [ruDate(row.date), ruDateTime(row.last_delivery)]);
calc.getRange(`V3:W${lastCalcRow}`).format = {
  fill: "#F3F4F6",
  font: { color: "#6B7280", size: 9 },
  numberFormat: "0.000000",
  borders: { preset: "all", style: "thin", color: "#E5E7EB" },
};
calc.getRange(`J4:J${lastCalcRow}`).formulas = dailyRows.map((_, i) => [[`=VLOOKUP(F${i + 4},$P$4:$Q$10,2,TRUE)`]][0]);
calc.getRange(`K4:K${lastCalcRow}`).formulas = dailyRows.map((_, i) => [[`=VLOOKUP(G${i + 4},$S$4:$T$8,2,TRUE)`]][0]);
calc.getRange(`L4:L${lastCalcRow}`).formulas = dailyRows.map((_, i) => [[`=IF(W${i + 4}="",0,MAX(0,ROUND((W${i + 4}-V${i + 4}-TIME(18,0,0))*1440,0)))`]][0]);
calc.getRange(`M4:M${lastCalcRow}`).formulas = dailyRows.map((_, i) => [[`=J${i + 4}+K${i + 4}+L${i + 4}*50`]][0]);
setTableBody(calc.getRange(`A3:M${lastCalcRow}`));
calc.getRange(`F4:F${lastCalcRow}`).format.numberFormat = "0.000";
calc.getRange(`J4:K${lastCalcRow}`).format.numberFormat = '# ##0 ₽';
calc.getRange(`M4:M${lastCalcRow}`).format.numberFormat = '# ##0 ₽';
calc.getRange(`L4:L${lastCalcRow}`).format.numberFormat = "0";
calc.getRange(`A4:M${lastCalcRow}`).format.wrapText = true;

calc.getRange("P2").values = [["Правило: вес"]];
calc.getRange("P2:Q2").format = { fill: "#E2F0D9", font: { bold: true }, horizontalAlignment: "center" };
calc.getRange("P3").values = ruleWeight;
setHeader(calc.getRange("P3:Q3"));
setTableBody(calc.getRange("P3:Q10"));
calc.getRange("Q4:Q10").format.numberFormat = '# ##0 ₽';

calc.getRange("S2").values = [["Правило: адреса"]];
calc.getRange("S2:T2").format = { fill: "#E2F0D9", font: { bold: true }, horizontalAlignment: "center" };
calc.getRange("S3").values = ruleAddress;
setHeader(calc.getRange("S3:T3"));
setTableBody(calc.getRange("S3:T8"));
calc.getRange("T4:T8").format.numberFormat = '# ##0 ₽';

calc.getRange("P12:T15").values = [
  ["Примечания", null, null, null, null],
  ["Адреса считаются по уникальному нормализованному адресу на водителя за день.", null, null, null, null],
  ["Если несколько заявок в маршрутном листе идут на один адрес, это один адрес.", null, null, null, null],
  ["Переработка = минуты после 18:00 * 50 рублей.", null, null, null, null],
];
calc.getRange("P12:T15").format = { fill: "#FFF7E6", wrapText: true, verticalAlignment: "top" };
calc.getRange("A:T").format.autofitColumns();

summary.getRange("A1").values = [["Свод водитель x месяц"]];
summary.getRange("A1:K1").format = { fill: "#0F172A", font: { color: "#FFFFFF", bold: true, size: 14 }, horizontalAlignment: "left" };
summary.getRange("A3:K3").values = [[
  "Водитель", "Месяц", "Дней", "Маршрутов", "Вес, кг", "Уникальных адресов",
  "Бонус вес", "Бонус адреса", "Переработка, мин", "Оплата переработки", "Итого бонус",
]];
setHeader(summary.getRange("A3:K3"));

const summaryRows = payload.summary_rows.map((row) => [row.driver, row.month, null, null, null, null, null, null, null, null, null]);
summary.getRange("A4").values = summaryRows;
const lastSummaryRow = 3 + summaryRows.length;
for (let r = 4; r <= lastSummaryRow; r += 1) {
  summary.getRange(`C${r}:K${r}`).formulas = [[
    `=COUNTIFS('Расчеты'!$C$4:$C$${lastCalcRow},A${r},'Расчеты'!$B$4:$B$${lastCalcRow},B${r})`,
    `=SUMIFS('Расчеты'!$E$4:$E$${lastCalcRow},'Расчеты'!$C$4:$C$${lastCalcRow},A${r},'Расчеты'!$B$4:$B$${lastCalcRow},B${r})`,
    `=SUMIFS('Расчеты'!$F$4:$F$${lastCalcRow},'Расчеты'!$C$4:$C$${lastCalcRow},A${r},'Расчеты'!$B$4:$B$${lastCalcRow},B${r})`,
    `=SUMIFS('Расчеты'!$G$4:$G$${lastCalcRow},'Расчеты'!$C$4:$C$${lastCalcRow},A${r},'Расчеты'!$B$4:$B$${lastCalcRow},B${r})`,
    `=SUMIFS('Расчеты'!$J$4:$J$${lastCalcRow},'Расчеты'!$C$4:$C$${lastCalcRow},A${r},'Расчеты'!$B$4:$B$${lastCalcRow},B${r})`,
    `=SUMIFS('Расчеты'!$K$4:$K$${lastCalcRow},'Расчеты'!$C$4:$C$${lastCalcRow},A${r},'Расчеты'!$B$4:$B$${lastCalcRow},B${r})`,
    `=SUMIFS('Расчеты'!$L$4:$L$${lastCalcRow},'Расчеты'!$C$4:$C$${lastCalcRow},A${r},'Расчеты'!$B$4:$B$${lastCalcRow},B${r})`,
    `=I${r}*50`,
    `=SUMIFS('Расчеты'!$M$4:$M$${lastCalcRow},'Расчеты'!$C$4:$C$${lastCalcRow},A${r},'Расчеты'!$B$4:$B$${lastCalcRow},B${r})`,
  ]];
}
const totalRow = lastSummaryRow + 2;
summary.getRange(`A${totalRow}:B${totalRow}`).values = [["Итого", null]];
summary.getRange(`C${totalRow}:K${totalRow}`).formulas = [[
  `=SUM(C4:C${lastSummaryRow})`,
  `=SUM(D4:D${lastSummaryRow})`,
  `=SUM(E4:E${lastSummaryRow})`,
  `=SUM(F4:F${lastSummaryRow})`,
  `=SUM(G4:G${lastSummaryRow})`,
  `=SUM(H4:H${lastSummaryRow})`,
  `=SUM(I4:I${lastSummaryRow})`,
  `=SUM(J4:J${lastSummaryRow})`,
  `=SUM(K4:K${lastSummaryRow})`,
]];
setTableBody(summary.getRange(`A3:K${totalRow}`));
summary.getRange(`A${totalRow}:K${totalRow}`).format = { fill: "#E2F0D9", font: { bold: true }, borders: { preset: "all", style: "thin", color: "#9BBB59" } };
summary.getRange(`E4:E${totalRow}`).format.numberFormat = "0.000";
summary.getRange(`G4:H${totalRow}`).format.numberFormat = '# ##0 ₽';
summary.getRange(`J4:K${totalRow}`).format.numberFormat = '# ##0 ₽';
summary.getRange(`A:K`).format.autofitColumns();

workbook.recalculate();

const calcPreview = await workbook.inspect({
  kind: "table",
  range: `Расчеты!A3:M${Math.min(lastCalcRow, 12)}`,
  include: "values,formulas",
  tableMaxRows: 12,
  tableMaxCols: 13,
});
console.log(calcPreview.ndjson);

const summaryPreview = await workbook.inspect({
  kind: "table",
  range: `Свод!A3:K${totalRow}`,
  include: "values,formulas",
  tableMaxRows: 20,
  tableMaxCols: 11,
});
console.log(summaryPreview.ndjson);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "formula error scan",
});
console.log(errors.ndjson);

await fs.mkdir(outputDir, { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(`OUTPUT ${outputPath}`);
