import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = "/Users/ghus/Desktop/um6p-rag/outputs/program_management_20260909";
const outputPath = `${outputDir}/Platform_Development_Tracker.xlsx`;

const phases = [
  ["Database Architecture", "Finalize the Hub, Actor, and Person table structures and relationships.", "Nouhaila & Ismail", new Date("2026-09-11T12:00:00"), "In progress"],
  ["Build the Map Development", "Connect people to organizations, add hub mapping and geography override, preserve background runs, and add completion notifications.", "Nouhaila", new Date("2026-09-15T12:00:00"), "In progress"],
  ["Verification Workflow", "Enable Verify and Verify All and define the information shown before approval.", "Nouhaila", new Date("2026-09-11T12:00:00"), "In progress"],
  ["Data Maintenance Agent", "Find and update actors and people in covered topics and apply agreed inclusion criteria.", "Ismail", new Date("2026-09-15T12:00:00"), "In progress"],
  ["Data Quality", "Improve deduplication, record merging, re-verification, and multi-organization affiliations.", "Ismail", new Date("2026-09-16T12:00:00"), "In progress"],
  ["Exports", "Align Excel and PowerPoint outputs with the finalized database architecture.", "Nouhaila", new Date("2026-09-11T12:00:00"), "In progress"],
  ["UI/UX Design", "Define the visual identity, refine the main user journeys, and design results and verification views.", "Nouhaila", new Date("2026-09-30T12:00:00"), "Not started"],
  ["Testing and Management Review", "Test functionality, accuracy, performance, and cost, then collect management feedback.", "Nouhaila & Ismail", new Date("2026-10-07T12:00:00"), "Not started"],
  ["Presentation and Rehearsal", "Prepare the platform comparison and complete the full presentation rehearsal.", "Nouhaila & Ismail", new Date("2026-10-07T12:00:00"), "Not started"],
];

const weekStarts = [
  new Date("2026-09-07T12:00:00"),
  new Date("2026-09-14T12:00:00"),
  new Date("2026-09-21T12:00:00"),
  new Date("2026-09-28T12:00:00"),
  new Date("2026-10-05T12:00:00"),
];

const wb = Workbook.create();
const ws = wb.worksheets.add("Development Plan");
ws.showGridLines = false;
ws.tabColor = "#17365D";

ws.getRange("A2:J2").format.borders = { bottom: { style: "medium", color: "#17365D" } };
ws.getRange("A2").values = [["Platform Development Plan"]];
ws.getRange("A2").format.font = { name: "Arial", size: 16, bold: true, color: "#17365D" };
ws.getRange("A3").values = [["Weekly deadline view | Updated September 9, 2026"]];
ws.getRange("A3").format.font = { name: "Arial", size: 10, italic: true, color: "#667085" };

ws.getRange("A5:J5").values = [["Phase", "Scope", "Responsible", "Deadline", "Status", ...weekStarts]];
ws.getRange("A5:J5").format = {
  fill: "#17365D",
  font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
  borders: { insideVertical: { style: "thin", color: "#FFFFFF" }, bottom: { style: "medium", color: "#17365D" } },
};
ws.getRange("F5:J5").setNumberFormat('"Week of "mmm d');

const rows = phases.map((phase) => {
  const deadline = phase[3];
  const timeline = weekStarts.map((start) => {
    const end = new Date(start);
    end.setDate(end.getDate() + 6);
    return deadline >= start && deadline <= end ? "◆" : "";
  });
  return [...phase, ...timeline];
});
ws.getRange("A6:J14").values = rows;
ws.getRange("A6:J14").format.font = { name: "Arial", size: 10, color: "#1F2937" };
ws.getRange("A6:J14").format.verticalAlignment = "center";
ws.getRange("A6:A14").format.font = { name: "Arial", size: 10, bold: true, color: "#17365D" };
ws.getRange("B6:B14").format.wrapText = true;
ws.getRange("C6:E14").format.horizontalAlignment = "center";
ws.getRange("D6:D14").setNumberFormat("mmm d, yyyy");
ws.getRange("F6:J14").format = {
  horizontalAlignment: "center",
  verticalAlignment: "center",
  font: { name: "Arial", size: 14, bold: true, color: "#FFFFFF" },
};

for (let r = 0; r < phases.length; r++) {
  const row = r + 6;
  const deadline = phases[r][3];
  const col = weekStarts.findIndex((start) => {
    const end = new Date(start);
    end.setDate(end.getDate() + 6);
    return deadline >= start && deadline <= end;
  });
  if (col >= 0) ws.getCell(row - 1, col + 5).format.fill = "#2F75B5";
  if (r % 2 === 1) ws.getRange(`A${row}:E${row}`).format.fill = "#F3F6FA";
}

ws.getRange("E6:E11").format = { fill: "#FFF2CC", font: { name: "Arial", size: 10, bold: true, color: "#7F6000" }, horizontalAlignment: "center", verticalAlignment: "center" };
ws.getRange("E12:E14").format = { fill: "#E7EAF0", font: { name: "Arial", size: 10, bold: true, color: "#475467" }, horizontalAlignment: "center", verticalAlignment: "center" };
ws.getRange("A6:J14").format.borders = { bottom: { style: "thin", color: "#D9E2F3" } };

ws.getRange("A16").values = [["◆"]];
ws.getRange("A16").format = { fill: "#2F75B5", font: { name: "Arial", size: 12, bold: true, color: "#FFFFFF" }, horizontalAlignment: "center" };
ws.getRange("B16").values = [["Deadline week"]];
ws.getRange("B16").format.font = { name: "Arial", size: 10, color: "#475467" };
ws.getRange("A17:J17").values = [["Dates shown are agreed completion deadlines; start dates and review dates are not included.", "", "", "", "", "", "", "", "", ""]];
ws.getRange("A17").format.font = { name: "Arial", size: 9, italic: true, color: "#667085" };

ws.getRange("A5:E14").format.borders = {
  insideVertical: { style: "thin", color: "#D9E2F3" },
  bottom: { style: "thin", color: "#D9E2F3" },
};
ws.getRange("F5:J14").format.borders = {
  insideVertical: { style: "thin", color: "#D9E2F3" },
  bottom: { style: "thin", color: "#D9E2F3" },
};

ws.getRange("A:A").format.columnWidth = 26;
ws.getRange("B:B").format.columnWidth = 58;
ws.getRange("C:C").format.columnWidth = 20;
ws.getRange("D:D").format.columnWidth = 17;
ws.getRange("E:E").format.columnWidth = 15;
ws.getRange("F:J").format.columnWidth = 14;
ws.getRange("2:2").format.rowHeight = 24;
ws.getRange("5:5").format.rowHeight = 34;
ws.getRange("6:14").format.rowHeight = 48;
ws.freezePanes.freezeRows(5);
ws.freezePanes.freezeColumns(1);

ws.getRange("E6:E14").dataValidation = { rule: { type: "list", values: ["Not started", "In progress", "Completed", "On hold"] } };

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
await fs.writeFile(`${outputDir}/preview.png`, new Uint8Array(await preview.arrayBuffer()));

await fs.mkdir(outputDir, { recursive: true });
const output = await SpreadsheetFile.exportXlsx(wb);
await output.save(outputPath);
console.log(outputPath);
