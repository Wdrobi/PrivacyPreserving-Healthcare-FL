import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = "E:/PrivacyPreserving-Healthcare-FL";
const sourcePath = path.join(
  workspaceDir,
  "output/presentation/Board-11_Group-2_CAABC-FL_Final_Defense_Conclusion_Paragraph.pptx",
);
const finalPath = path.join(
  workspaceDir,
  "output/presentation/Board-11_Group-2_CAABC-FL_Final_Defense_With_Experimental_Setup_v2.pptx",
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

// Duplicate Data Analysis Methods and place Experimental Setup immediately after it,
// before Budget Plan and the Results section.
const slide = presentation.slides.getItem(22).duplicate();
slide.moveTo(23);

const BLUE = "#17365D";
const TITLE_BLUE = "#062B6F";
const GREEN = "#008A46";
const TEXT = "#263244";
const BORDER = "#9CA9B7";
const FONT = "Arial";

const title = slide.placeholders.getItem("title");
if (!title) throw new Error("Duplicated setup slide has no title placeholder.");
title.text.replace("Data Analysis Methods", "Experimental Setup");
title.text.style = {
  typeface: FONT,
  fontSize: 42,
  bold: true,
  color: TITLE_BLUE,
  alignment: "center",
  verticalAlignment: "middle",
  autoFit: "shrinkText",
};

// Hide duplicated body content while retaining the university template chrome.
slide.shapes.add({
  geometry: "rect",
  name: "experimental-setup-cover",
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
  "experimental-setup-caption",
  "Frozen protocol used for paired utility, privacy, robustness, and systems evaluation",
  { left: 110, top: 118, width: 1060, height: 34 },
  { fontSize: 17, italic: true, color: "#5B677A", alignment: "center", verticalAlignment: "middle" },
);

const values = [
  ["Component", "Registered configuration"],
  [
    "Dataset and split",
    "PhysioNet/CinC 2019 sepsis cohort: 40,336 patients from two natural hospitals; stratified 70/15/15 train, validation, and locked test partitions.",
  ],
  [
    "Model and training",
    "280–64–1 multilayer perceptron with 18,049 parameters; 20 federated rounds, one local epoch, batch size 128, and learning rate 0.03.",
  ],
  [
    "Privacy and encryption",
    "Patient clipping C = 1.0, Gaussian noise multiplier σ = 1.2, δ = 10⁻⁵, and RDP accounting; TenSEAL CKKS with N = 8192 and scale 2⁴⁰.",
  ],
  [
    "CAABC-FL configuration",
    "256-coordinate blocks, two encrypted update chunks, support refresh every five rounds, and error feedback for discarded coordinates.",
  ],
  [
    "Security evaluation",
    "LiRA and RMIA with eight reference models per seed; 300-step gradient reconstruction; 20 virtual clients, seven poisoning attacks, and 10–40% malicious participation.",
  ],
  [
    "Replication and analysis",
    "Ten paired seeds for the core protected comparison and five for secondary security comparisons; paired 95% t intervals with Holm correction.",
  ],
];

const table = slide.tables.add({
  rows: values.length,
  columns: 2,
  left: 100,
  top: 160,
  width: 1080,
  height: 430,
  columnWidths: [245, 835],
  values,
});
table.borders.assign({ style: "solid", fill: BORDER, width: 1 });
table.cells.block({ row: 0, column: 0, rowCount: values.length, columnCount: 2 }).assign({
  fill: "#FFFFFF",
  textStyle: { typeface: FONT, fontSize: 15.8, color: TEXT },
  margins: { left: 8, right: 8, top: 5, bottom: 5 },
  anchor: "middle",
});
table.cells.block({ row: 0, column: 0, rowCount: 1, columnCount: 2 }).assign({
  fill: BLUE,
  textStyle: { typeface: FONT, fontSize: 17, color: "#FFFFFF", bold: true },
  anchor: "middle",
});
table.cells.block({ row: 1, column: 0, rowCount: values.length - 1, columnCount: 1 }).assign({
  fill: "#EAF4F0",
  textStyle: { typeface: FONT, fontSize: 15.8, color: GREEN, bold: true },
  anchor: "middle",
});
table.styleOptions = { headerRow: true, bandedRows: true };

addText(
  "experimental-setup-lock-note",
  "The protocol, decision rules, and operating thresholds were frozen before confirmatory test access.",
  { left: 115, top: 600, width: 1050, height: 34 },
  { fontSize: 15.5, italic: true, color: GREEN, alignment: "center", verticalAlignment: "middle" },
);

// Reassert the two logos because imported image relationships can disappear
// after duplication in some PowerPoint readers. The original border and footer
// remain intact on this source slide.
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

slide.speakerNotes.textFrame.setText(
  "This slide summarizes the frozen experimental protocol. We used the full 40,336-patient PhysioNet 2019 sepsis cohort and preserved its two natural hospital partitions. Every paired method used the same patient split, initialization seed, model, and 20-round training budget. The private path used patient-level clipping, Gaussian noise, RDP accounting, and real TenSEAL CKKS. The security evaluation included powered membership inference, 300-step gradient reconstruction, and poisoning experiments with up to 40 percent malicious clients. The model seed is the statistical unit. Core protected methods used ten paired seeds, while secondary and security comparisons used five paired seeds. The test partition remained locked until the protocol and decision rules were frozen.",
);

// Add Experimental Setup to the Proposed Methodology list in the contents slide.
const toc = presentation.slides.getItem(1);
function addTocText(name, text, position, style = {}) {
  const shape = toc.shapes.add({
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
    color: TITLE_BLUE,
    verticalAlignment: "middle",
    autoFit: "shrinkText",
    ...style,
  };
  return shape;
}
addTocText("toc-methodology-chevron-4", "›", { left: 727, top: 262, width: 22, height: 23 }, { fontSize: 20 });
addTocText("toc-methodology-item-4", "Experimental setup", { left: 757, top: 262, width: 430, height: 23 }, { fontSize: 17 });

// Renumber the inserted slide and every following slide.
for (let index = 0; index < presentation.slides.items.length; index += 1) {
  const current = presentation.slides.getItem(index);
  const pageShape = current.shapes.items.find((shape) => (
    shape.position?.left >= 1175
    && shape.position?.top >= 630
    && shape.position?.height >= 40
  ));
  if (!pageShape) continue;
  const actualNumber = String(index + 1);
  const previousNumber = index < 23 ? actualNumber : (index === 23 ? "23" : String(index));
  pageShape.text.replace(previousNumber, actualNumber);
}

const candidatePath = path.join(
  stagingDir,
  "Board-11_Group-2_CAABC-FL_Final_Defense_With_Experimental_Setup_candidate.pptx",
);
await (await PresentationFile.exportPptx(presentation)).save(candidatePath);

const tableOwners = [11, 12, 13, 14, 24, 25, 28, 38];
const result = await finalizePresentation({
  explicitTotalSlideCount: 41,
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
  requiredNativeChartOwnerSlides: [7, 28],
  nativeChartTargetApplication: "powerpoint",
  fontPolicy: {
    basis: "reference",
    families: ["Arial", "Corbel"],
    referencePath: sourcePath,
    referenceSha256: "b0a56144f3f3037ee0dbf28d7b5d112c98f122ed620fe688376e65bd66112334",
  },
  verifyArtifactToolImport: true,
  receiptPath: path.join(
    stagingDir,
    "Board-11_Group-2_CAABC-FL_Final_Defense_With_Experimental_Setup_v2.validation.json",
  ),
});

console.log(JSON.stringify({ finalPath, slideCount: presentation.slides.items.length, result }, null, 2));
