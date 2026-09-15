import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const outputDir = "/Users/ghus/Desktop/um6p-rag/outputs/program_management_20260909";
const outputPath = `${outputDir}/Platform_Development_Tracker.xlsx`;
const input = await FileBlob.load(outputPath);
const wb = await SpreadsheetFile.importXlsx(input);
const ws = wb.worksheets.getItem("Development Plan");

const orange = "#D7410B";
const charcoal = "#3D3935";
const paleOrange = "#F6D7CB";
const rowTint = "#FBF2ED";
const line = "#E8C6B9";

ws.tabColor = orange;
ws.getRange("A2:J2").format.borders = { bottom: { style: "medium", color: orange } };
ws.getRange("A2").format.font = { name: "Arial", size: 16, bold: true, color: orange };
ws.getRange("A5:J5").format = {
  fill: orange,
  font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
  borders: { insideVertical: { style: "thin", color: "#FFFFFF" }, bottom: { style: "medium", color: orange } },
};
ws.getRange("A6:A14").format.font = { name: "Arial", size: 10, bold: true, color: charcoal };

for (const row of [7, 9, 11, 13]) {
  ws.getRange(`A${row}:E${row}`).format.fill = rowTint;
}
for (const row of [6, 8, 10, 12, 14]) {
  ws.getRange(`A${row}:D${row}`).format.fill = "#FFFFFF";
}

ws.getRange("E6:E11").format = {
  fill: paleOrange,
  font: { name: "Arial", size: 10, bold: true, color: orange },
  horizontalAlignment: "center",
  verticalAlignment: "center",
};
ws.getRange("A6:E14").format.borders = {
  insideVertical: { style: "thin", color: line },
  bottom: { style: "thin", color: line },
};
ws.getRange("F5:J14").format.borders = {
  insideVertical: { style: "thin", color: line },
  bottom: { style: "thin", color: line },
};

for (const cell of ["F6", "G7", "F8", "G9", "G10", "F11", "I12", "J13", "J14"]) {
  ws.getRange(cell).format.fill = orange;
}
ws.getRange("A16").format = {
  fill: orange,
  font: { name: "Arial", size: 12, bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
};

wb.recalculate();

const check = await wb.inspect({
  kind: "table",
  range: "Development Plan!A2:J17",
  include: "values,formulas",
  tableMaxRows: 20,
  tableMaxCols: 12,
});
console.log(check.ndjson);

const errors = await wb.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
});
console.log(errors.ndjson);

const preview = await wb.render({ sheetName: "Development Plan", range: "A1:J17", scale: 1.4, format: "png" });
await fs.writeFile(`${outputDir}/preview-orange.png`, new Uint8Array(await preview.arrayBuffer()));

const output = await SpreadsheetFile.exportXlsx(wb);
await output.save(outputPath);
console.log(outputPath);
