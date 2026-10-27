import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = "E:/PrivacyPreserving-Healthcare-FL";
const sourcePath = path.join(
  workspaceDir,
  "output/presentation/CAABC-FL_Final_Defense_25_September_2026_Related_Studies_Final.pptx",
);
const finalPath = path.join(
  workspaceDir,
  "output/presentation/CAABC-FL_Final_Defense_25_September_2026_Related_Studies_Comparison_v3.pptx",
);
const stagingDir = path.join(workspaceDir, ".codex-finalizer");
const skillDir = "C:/Users/HP/.codex/plugins/cache/openai-primary-runtime/presentations/26.909.12148/skills/presentations";
const runtimePython = "C:/Users/HP/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe";

const { finalizePresentation } = await import(
  pathToFileURL(path.join(skillDir, "container_tools/artifact_tool_utils.mjs")).href,
);

await fs.mkdir(stagingDir, { recursive: true });
await fs.mkdir(path.dirname(finalPath), { recursive: true });

const presentation = await PresentationFile.importPptx(await FileBlob.load(sourcePath));
const slide = presentation.slides.getItem(12).duplicate();
slide.moveTo(13);

const BLUE = "#1E3A5F";
const GREEN = "#008A46";
const TEXT = "#1F2937";
const MUTED = "#52606D";
const BORDER = "#9CA9B7";
const FONT = "Arial";

const title = slide.placeholders.getItem("title");
if (!title) throw new Error("Duplicated related-studies slide has no title placeholder.");
title.text.replace("Related Studies (3/3)", "Comparison of Related Studies");
title.text.style = {
  typeface: "Arial",
  fontSize: 42,
  bold: true,
  color: "#062B6F",
  alignment: "center",
  verticalAlignment: "middle",
  autoFit: "shrinkText",
};

// Hide the duplicated content while retaining the university master, logos, and footer.
slide.shapes.add({
  geometry: "rect",
  name: "related-comparison-cover",
  position: { left: 45, top: 112, width: 1190, height: 535 },
  fill: "#FFFFFF",
  line: { fill: "none", width: 0 },
});

function addText(name, text, position, style = {}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    name,
    position,
    fill: "none",
    line: { fill: "none", width: 0 },
  });
  shape.text = text;
  shape.text.style = {
    typeface: FONT,
    fontSize: 17,
    color: TEXT,
    autoFit: "shrinkText",
    ...style,
  };
  return shape;
}

async function addImage(filePath, position, alt) {
  const bytes = new Uint8Array(await fs.readFile(filePath));
  return slide.images.add({
    blob: bytes,
    contentType: path.extname(filePath).toLowerCase() === ".jpg" ? "image/jpeg" : "image/png",
    alt,
    fit: "contain",
    position,
  });
}

addText(
  "related-comparison-caption",
  "TABLE I. Comparison of the closest privacy-preserving federated-learning studies",
  { left: 95, top: 120, width: 1090, height: 32 },
  { fontSize: 18, italic: true, color: BLUE, alignment: "center", verticalAlignment: "middle" },
);

const values = [
  ["Study", "Year", "Method", "Main contribution", "Limitation relative to this thesis"],
  [
    "Stevens et al.\nFLDP [11]",
    "2022",
    "LWE secure aggregation with distributed DP",
    "Malicious-secure private aggregation with measured communication and server cost",
    "No poisoning defence; non-clinical benchmarks and a different cryptographic path",
  ],
  [
    "Froelicher et al.\nFAMHE [12]",
    "2021",
    "Multiparty homomorphic encryption",
    "Protected biomedical survival and genomic analytics without a central decryptor",
    "Not iterative neural FL; no adaptive compression or poisoning evaluation",
  ],
  [
    "Xu et al.\nDDFed [16]",
    "2024",
    "FHE with encrypted anomaly detection",
    "Combines update confidentiality with poisoning detection in cross-device and cross-silo FL",
    "No formal record-level DP, ciphertext-aware compression, or external governance",
  ],
  [
    "Gu et al.\nDP-BREM+ [17]",
    "2025",
    "Secure aggregation, client momentum, and DP",
    "Combines formal privacy and Byzantine robustness without a trusted server",
    "No encrypted wire-reduction method, clinical cohort, or external audit ledger",
  ],
  [
    "Asi et al.\nPREAMBLE [18]",
    "2025",
    "Two-server block-sparse private aggregation",
    "Co-designs block sparsity and protected transport for high-dimensional vectors",
    "Requires non-colluding servers; no poisoning or end-to-end clinical FL",
  ],
];

const table = slide.tables.add({
  rows: values.length,
  columns: 5,
  left: 55,
  top: 160,
  width: 1170,
  height: 420,
  columnWidths: [175, 78, 225, 335, 357],
  values,
});
table.borders.assign({ style: "solid", fill: BORDER, width: 1 });
table.cells.block({ row: 0, column: 0, rowCount: values.length, columnCount: 5 }).assign({
  fill: "#FFFFFF",
  textStyle: { typeface: FONT, fontSize: 14.8, color: TEXT },
  margins: { left: 6, right: 6, top: 4, bottom: 4 },
  anchor: "middle",
});
table.cells.block({ row: 0, column: 0, rowCount: 1, columnCount: 5 }).assign({
  fill: BLUE,
  textStyle: { typeface: FONT, fontSize: 15.5, color: "#FFFFFF", bold: true },
  anchor: "middle",
});
table.cells.block({ row: 1, column: 0, rowCount: values.length - 1, columnCount: 1 }).assign({
  fill: "#EAF4F8",
  textStyle: { typeface: FONT, fontSize: 14.8, color: BLUE, bold: true },
  anchor: "middle",
});
table.cells.block({ row: 1, column: 1, rowCount: values.length - 1, columnCount: 1 }).assign({
  fill: "#F2F5F7",
  textStyle: { typeface: FONT, fontSize: 14.8, color: TEXT },
  anchor: "middle",
});
table.styleOptions = { headerRow: true, bandedRows: true };

addText(
  "related-comparison-note",
  "The studies use different datasets, privacy definitions, and threat models; the table compares scope rather than rank.",
  { left: 95, top: 595, width: 1090, height: 42 },
  { fontSize: 15.5, italic: true, color: MUTED, alignment: "center", verticalAlignment: "middle" },
);

slide.speakerNotes.textFrame.setText(
  "This table compares five anchor studies that contribute directly to the design space of this thesis. FLDP and FAMHE establish protected aggregation and biomedical multiparty computation. DDFed and DP-BREM+ integrate privacy with poisoning or Byzantine robustness. PREAMBLE aligns block sparsity with private transport. The table reports scope rather than a numerical ranking because the studies use different datasets, cryptographic assumptions, and threat models. Sources: Stevens et al., USENIX Security 2022; Froelicher et al., Nature Communications 2021; Xu et al., NeurIPS 2024; Gu et al., USENIX Security 2025; Asi et al., NeurIPS 2025.",
);

// Reassert the university slide chrome because duplicated imported images can
// remain present in OOXML but fail to render in the duplicated slide.
slide.shapes.add({
  geometry: "rect",
  name: "related-comparison-border",
  position: { left: 30, top: 31, width: 1240, height: 664 },
  fill: "none",
  line: { fill: "#222222", width: 1.2 },
});
slide.shapes.add({
  geometry: "rect",
  name: "related-comparison-footer-rule",
  position: { left: 45, top: 665, width: 1190, height: 1 },
  fill: "#C8D9A5",
  line: { fill: "none", width: 0 },
});
await addImage(
  path.join(workspaceDir, "tmp/ppt_assets/image1.jpg"),
  { left: 38, top: 39, width: 72, height: 72 },
  "Computer Science and Engineering emblem",
);
await addImage(
  path.join(workspaceDir, "tmp/ppt_assets/image2.png"),
  { left: 1041, top: 26, width: 204, height: 85 },
  "Green University of Bangladesh logo",
);
addText(
  "related-comparison-date",
  "25 September 2026",
  { left: 49, top: 670, width: 190, height: 22 },
  { fontSize: 12, color: BLUE, verticalAlignment: "middle" },
);
// Inserting the comparison slide shifts every later hard-coded page number.
const pageSnapshot = await presentation.inspect({
  kind: "textbox",
  include: "id,slide,text,bbox",
  maxChars: 180000,
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
  "CAABC-FL_Final_Defense_25_September_2026_Related_Studies_Comparison_candidate.pptx",
);
await (await PresentationFile.exportPptx(presentation)).save(candidatePath);

const tableOwners = [11, 12, 13, 14, 22, 25, 34];
const result = await finalizePresentation({
  explicitTotalSlideCount: 37,
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
  requiredNativeChartOwnerSlides: [7, 25],
  nativeChartTargetApplication: "powerpoint",
  fontPolicy: {
    basis: "reference",
    families: ["Arial", "Corbel"],
    referencePath: sourcePath,
    referenceSha256: "2b4e4527a857bf84501d644c085aef113688590d36442974bd1490d5beb88d56",
  },
  verifyArtifactToolImport: true,
  receiptPath: path.join(
    stagingDir,
    "CAABC-FL_Final_Defense_25_September_2026_Related_Studies_Comparison_v3.validation.json",
  ),
});

console.log(JSON.stringify({ finalPath, slideCount: presentation.slides.items.length, result }, null, 2));
