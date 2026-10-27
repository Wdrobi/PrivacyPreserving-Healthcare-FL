import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = "E:/PrivacyPreserving-Healthcare-FL";
const sourcePath = path.join(
  workspaceDir,
  "output/presentation/CAABC-FL_Final_Defense_25_September_2026_Background_Visual_Reviewed.pptx",
);
const finalPath = path.join(
  workspaceDir,
  "output/presentation/CAABC-FL_Final_Defense_25_September_2026_Motivation_Evidence_Reviewed.pptx",
);
const stagingDir = path.join(workspaceDir, ".codex-finalizer");
const skillDir = "C:/Users/HP/.codex/plugins/cache/openai-primary-runtime/presentations/26.909.12148/skills/presentations";
const runtimePython = "C:/Users/HP/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe";

const { finalizePresentation, applyPresentationChartFont } = await import(
  pathToFileURL(path.join(skillDir, "container_tools/artifact_tool_utils.mjs")).href,
);

await fs.mkdir(stagingDir, { recursive: true });
await fs.mkdir(path.dirname(finalPath), { recursive: true });

const presentation = await PresentationFile.importPptx(await FileBlob.load(sourcePath));
const motivationSource = presentation.slides.getItem(5);
const evidenceSlide = motivationSource.duplicate();
evidenceSlide.moveTo(6);
evidenceSlide.placeholders.getItem("title").text = "Evidence for Collaboration";

const removeNames = [
  "motivation-heading-0", "motivation-heading-1", "motivation-heading-2", "motivation-heading-3",
  "motivation-body-0", "motivation-body-1", "motivation-body-2", "motivation-body-3",
  "motivation-close",
  "rule-105-255", "rule-397-255", "rule-689-255", "rule-981-255",
];
for (const name of removeNames) evidenceSlide.shapes.getItem(name)?.delete();

const addText = (name, value, position, style) => {
  const item = evidenceSlide.shapes.add({
    geometry: "textbox",
    name,
    position,
    fill: "none",
    line: { fill: "none", width: 0 },
  });
  item.text = value;
  item.text.style = {
    typeface: "Arial",
    color: "#1F2937",
    autoFit: "shrinkText",
    ...style,
  };
  return item;
};

addText(
  "evidence-sites-number",
  "20",
  { left: 95, top: 150, width: 235, height: 120 },
  { fontSize: 72, bold: true, color: "#008A46", alignment: "center", verticalAlignment: "middle" },
);
addText(
  "evidence-sites-label",
  "clinical sites across four continents",
  { left: 80, top: 260, width: 270, height: 85 },
  { fontSize: 24, bold: true, color: "#1E3A5F", alignment: "center", verticalAlignment: "top" },
);
addText(
  "evidence-cases-number",
  "16,148",
  { left: 70, top: 350, width: 290, height: 95 },
  { fontSize: 54, bold: true, color: "#1E3A5F", alignment: "center", verticalAlignment: "middle" },
);
addText(
  "evidence-cases-label",
  "cases in the EXAM federated cohort [3]",
  { left: 80, top: 440, width: 270, height: 70 },
  { fontSize: 22, color: "#1F2937", alignment: "center", verticalAlignment: "top" },
);

const separator = evidenceSlide.shapes.add({
  geometry: "rect",
  name: "evidence-separator",
  position: { left: 405, top: 150, width: 3, height: 365 },
  fill: "#008A46",
  line: { fill: "none", width: 0 },
});
separator.sendToBack();

const chart = evidenceSlide.charts.add("bar", {
  position: { left: 465, top: 140, width: 730, height: 370 },
  title: "Average AUC on participating sites",
  titlePlacement: "aboveChart",
  titleTextStyle: { typeface: "Arial", fontSize: 25, bold: true, fill: "#1E3A5F" },
  categories: ["Local models", "EXAM federated model"],
  series: [{
    name: "AUC",
    values: [0.795, 0.920],
    valuesFormatCode: "0.000",
    fill: "#1E3A5F",
    points: [
      { idx: 0, fill: "#1E3A5F" },
      { idx: 1, fill: "#008A46" },
    ],
  }],
  barOptions: { direction: "column", grouping: "clustered", gapWidth: 70, varyColors: true },
  hasLegend: false,
  xAxis: {
    visible: true,
    textStyle: { typeface: "Arial", fontSize: 19, fill: "#1F2937" },
    line: { style: "solid", fill: "#94A3B8", width: 1 },
  },
  yAxis: {
    visible: true,
    title: { text: "AUC", textStyle: { typeface: "Arial", fontSize: 18, fill: "#475569" } },
    min: 0.70,
    max: 1.00,
    majorUnit: 0.05,
    numberFormatCode: "0.00",
    textStyle: { typeface: "Arial", fontSize: 16, fill: "#475569" },
    majorGridlines: { style: "solid", fill: "#E2E8F0", width: 1 },
    line: { style: "solid", fill: "#94A3B8", width: 1 },
  },
  dataLabels: {
    showValue: true,
    position: "outEnd",
    textStyle: { typeface: "Arial", fontSize: 20, bold: true, fill: "#1F2937" },
  },
  chartFill: "#FFFFFF",
  chartLine: { fill: "none", width: 0 },
  plotAreaFill: "#FFFFFF",
  plotAreaLine: { fill: "none", width: 0 },
});
applyPresentationChartFont(chart, { fontFamily: "Arial" });

addText(
  "evidence-chart-caption",
  "EXAM improved the mean site-level AUC from 0.795 to 0.920 [3].",
  { left: 500, top: 500, width: 660, height: 45 },
  { fontSize: 18, italic: true, color: "#475569", alignment: "center", verticalAlignment: "middle" },
);
addText(
  "evidence-sheller",
  "Federated training across 10 institutions reached 99% of centralized model quality [2].",
  { left: 100, top: 565, width: 1080, height: 58 },
  { fontSize: 23, bold: true, color: "#008A46", alignment: "center", verticalAlignment: "middle" },
);

evidenceSlide.speakerNotes.textFrame.setText(
  "Published healthcare studies motivate multi-institutional learning. Sheller et al. reported that federated training across 10 institutions reached 99% of the model quality achieved with centralized data. The EXAM study trained on 16,148 cases from 20 clinical sites across four continents and reported an average local-test AUC increase from 0.795 for local models to 0.920 for the federated model. These results establish the value of collaboration, while this thesis addresses the remaining privacy, encrypted communication, poisoning, and governance challenges. Sources: Sheller et al., Scientific Reports 10, 12598 (2020), doi:10.1038/s41598-020-69250-1; Dayan et al., Nature Medicine 27, 1735–1743 (2021), doi:10.1038/s41591-021-01506-3.",
);

// Inserting the evidence slide shifts every later hard-coded page number.
const pageSnapshot = await presentation.inspect({
  kind: "textbox",
  include: "id,slide,text,bbox",
  maxChars: 140000,
});
for (const line of pageSnapshot.ndjson.split("\n").filter(Boolean)) {
  const record = JSON.parse(line);
  const [left, top] = record.bbox ?? [0, 0, 0, 0];
  if (record.slide > 1 && top > 620 && left > 1100) {
    presentation.resolve(record.id).text = String(record.slide);
  }
}

const candidatePath = path.join(
  stagingDir,
  "CAABC-FL_Final_Defense_25_September_2026_Motivation_Evidence_Reviewed_candidate.pptx",
);
await (await PresentationFile.exportPptx(presentation)).save(candidatePath);

const tableOwners = [11, 12, 13, 21, 24, 33];
const result = await finalizePresentation({
  explicitTotalSlideCount: 36,
  sourceTemplatePath: sourcePath,
  workspaceDir,
  candidatePath,
  finalPath,
  pythonExecutable: runtimePython,
  integrityValidatorPath: path.join(skillDir, "container_tools/inspect_presentation_package_integrity.py"),
  layoutValidatorPath: path.join(skillDir, "container_tools/inspect_presentation_layout_geometry.py"),
  layoutArgs: [
    "--expected-slide-size-emu", "12192000,6858000",
    "--validate-bullet-geometry",
    "--validate-heading-fit",
    ...tableOwners.flatMap((number) => ["--require-native-table-slide", String(number)]),
  ],
  requiredNativeTableOwnerSlides: tableOwners,
  requiredNativeChartOwnerSlides: [7, 24],
  materializeLiteralChartWorkbooks: true,
  nativeChartTargetApplication: "powerpoint",
  fontPolicy: {
    basis: "reference",
    families: ["Arial", "Corbel"],
    referencePath: sourcePath,
    referenceSha256: "a5318449bbfd3ea6a19c5a4bff773784585e3d05bbbd7584ef028507668b3f36",
  },
  verifyArtifactToolImport: true,
  receiptPath: path.join(
    stagingDir,
    "CAABC-FL_Final_Defense_25_September_2026_Motivation_Evidence_Reviewed.validation.json",
  ),
});

console.log(JSON.stringify({ finalPath, evidenceSlide: evidenceSlide.index + 1, result }, null, 2));
