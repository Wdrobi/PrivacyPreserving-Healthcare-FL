import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = "E:/PrivacyPreserving-Healthcare-FL";
const sourcePath = "C:/Users/HP/Downloads/Board-11_Group-2_CAABC-FL_Final_Defense.pptx";
const finalPath = path.join(
  workspaceDir,
  "output/presentation/Board-11_Group-2_CAABC-FL_Final_Defense_Conceptual_Framework_v2.pptx",
);
const stagingDir = path.join(workspaceDir, ".codex-finalizer");
const previewDir = path.join(workspaceDir, "tmp/ppt_build/conceptual_framework_after");
const skillDir = "C:/Users/HP/.codex/plugins/cache/openai-primary-runtime/presentations/26.909.12148/skills/presentations";
const runtimePython = "C:/Users/HP/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe";

const { finalizePresentation } = await import(
  pathToFileURL(path.join(skillDir, "container_tools/artifact_tool_utils.mjs")).href,
);

await fs.mkdir(stagingDir, { recursive: true });
await fs.mkdir(previewDir, { recursive: true });
await fs.mkdir(path.dirname(finalPath), { recursive: true });

const presentation = await PresentationFile.importPptx(await FileBlob.load(sourcePath));
const slide = presentation.resolve("sl/gny5sjyp");
if (!slide) throw new Error("Conceptual Framework slide not found.");

const before = await slide.export({ format: "png", scale: 2 });
await fs.writeFile(
  path.join(previewDir, "slide-16-before.png"),
  new Uint8Array(await before.arrayBuffer()),
);

const FONT = "Arial";
const NAVY = "#062B6F";
const TEXT = "#263244";
const MUTED = "#58667A";
const GREEN = "#008A46";
const GREEN_LINE = "#3B8F5A";
const GREEN_FILL = "#EEF8F0";
const INPUT_FILL = "#EEF2FF";
const INPUT_LINE = "#748DB7";
const OUTCOME_FILL = "#FFF3E6";
const OUTCOME_LINE = "#C98234";
const BOUND_FILL = "#FFF2F2";
const BOUND_LINE = "#B96A6A";

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
    fontSize: 16,
    color: TEXT,
    alignment: "center",
    verticalAlignment: "middle",
    autoFit: "shrinkText",
    ...style,
  };
  return shape;
}

function addBox(name, position, fill, lineFill, lineStyle = "solid", radius = true) {
  return slide.shapes.add({
    geometry: radius ? "roundRect" : "rect",
    name,
    position,
    fill,
    line: { style: lineStyle, fill: lineFill, width: 1.4 },
  });
}

function addRightArrow(name, left, top) {
  slide.shapes.add({
    geometry: "rightArrow",
    name,
    position: { left, top, width: 18, height: 18 },
    fill: NAVY,
    line: { fill: NAVY, width: 0.5 },
  });
}

function addDownArrow(name, left, top, height = 22) {
  slide.shapes.add({
    geometry: "downArrow",
    name,
    position: { left, top, width: 18, height },
    fill: NAVY,
    line: { fill: NAVY, width: 0.5 },
  });
}

// Cover only the slide body. The title, university logos, footer, date and page
// number remain exactly as supplied by the user's manually formatted deck.
slide.shapes.add({
  geometry: "rect",
  name: "conceptual-framework-replacement-cover",
  position: { left: 55, top: 115, width: 1170, height: 525 },
  fill: "#FFFFFF",
  line: { fill: "none", width: 0 },
});

// Stage 1: research inputs.
addBox(
  "stage-1-inputs",
  { left: 125, top: 128, width: 1030, height: 70 },
  INPUT_FILL,
  INPUT_LINE,
);
addText(
  "stage-1-title",
  "STAGE 1  RESEARCH INPUTS",
  { left: 420, top: 134, width: 440, height: 22 },
  { fontSize: 15.5, bold: true, color: NAVY },
);
const inputLabels = [
  ["Natural hospital partitions", 150],
  ["Threat and trust model", 490],
  ["Research objectives", 830],
];
for (const [label, left] of inputLabels) {
  addText(
    `stage-1-${String(label).toLowerCase().replace(/[^a-z]+/g, "-")}`,
    label,
    { left, top: 162, width: 300, height: 27 },
    { fontSize: 15, color: TEXT },
  );
}
slide.shapes.add({
  geometry: "rect",
  name: "stage-1-divider-1",
  position: { left: 465, top: 164, width: 1.2, height: 22 },
  fill: "#B8C5D8",
  line: { fill: "none", width: 0 },
});
slide.shapes.add({
  geometry: "rect",
  name: "stage-1-divider-2",
  position: { left: 805, top: 164, width: 1.2, height: 22 },
  fill: "#B8C5D8",
  line: { fill: "none", width: 0 },
});
addDownArrow("stage-1-to-2", 631, 199, 22);

// Stage 2: protection pipeline.
addText(
  "stage-2-title",
  "Stage 2  Protection pipeline",
  { left: 430, top: 210, width: 420, height: 32 },
  { fontSize: 21, bold: true, color: NAVY },
);

const steps = [
  {
    left: 75,
    title: "Local learning",
    body: "On-site preprocessing\nPatient-level DP",
  },
  {
    left: 303,
    title: "Communication control",
    body: "CAABC-FL common support\nResidual feedback",
  },
  {
    left: 531,
    title: "Confidentiality and identity",
    body: "CKKS encryption\nSignatures and mTLS",
  },
  {
    left: 759,
    title: "Integrity control",
    body: "Validation and reputation\nRollback and quarantine",
  },
  {
    left: 987,
    title: "Governance",
    body: "Aggregate verification\nAudit quorum and release policy",
  },
];

for (let index = 0; index < steps.length; index += 1) {
  const step = steps[index];
  addBox(
    `stage-2-box-${index + 1}`,
    { left: step.left, top: 250, width: 210, height: 138 },
    GREEN_FILL,
    GREEN_LINE,
  );
  addText(
    `stage-2-title-${index + 1}`,
    step.title,
    { left: step.left + 10, top: 262, width: 190, height: 40 },
    { fontSize: 17, bold: true, color: "#174C2E" },
  );
  addText(
    `stage-2-body-${index + 1}`,
    step.body,
    { left: step.left + 13, top: 306, width: 184, height: 66 },
    { fontSize: 14.5, color: TEXT },
  );
  if (index < steps.length - 1) addRightArrow(`stage-2-arrow-${index + 1}`, step.left + 210, 310);
}

addDownArrow("stage-2-to-3", 631, 394, 23);

// Stage 3: measurable outcomes.
addBox(
  "stage-3-outcomes",
  { left: 125, top: 420, width: 1030, height: 94 },
  OUTCOME_FILL,
  OUTCOME_LINE,
);
addText(
  "stage-3-title",
  "STAGE 3  MEASURABLE OUTCOMES",
  { left: 420, top: 429, width: 440, height: 22 },
  { fontSize: 15.5, bold: true, color: "#7A4616" },
);
const outcomes = [
  "Utility and\ncalibration",
  "Formal and empirical\nprivacy",
  "Encrypted upload\nand latency",
  "Poisoning\nresponse",
  "Correctness and\navailability",
];
for (let index = 0; index < outcomes.length; index += 1) {
  addText(
    `stage-3-outcome-${index + 1}`,
    outcomes[index],
    { left: 145 + index * 198, top: 459, width: 190, height: 43 },
    { fontSize: 14.5, color: TEXT },
  );
}

addDownArrow("stage-3-to-4", 631, 518, 22);

// Stage 4: explicit claim boundary.
addBox(
  "stage-4-bounded-evidence",
  { left: 270, top: 544, width: 740, height: 77 },
  BOUND_FILL,
  BOUND_LINE,
  "dashed",
);
addText(
  "stage-4-title",
  "STAGE 4  BOUNDED RESEARCH EVIDENCE",
  { left: 410, top: 550, width: 460, height: 23 },
  { fontSize: 15.5, bold: true, color: "#813B3B" },
);
addText(
  "stage-4-body",
  "Evidence is limited to the evaluated data, attacks, seeds and deployment environment.\nNo universal, clinical, regulatory or production-security claim.",
  { left: 310, top: 576, width: 660, height: 36 },
  { fontSize: 14.2, color: MUTED },
);

slide.speakerNotes.textFrame.setText(
  "This framework moves from research inputs to bounded evidence. The inputs are the natural hospital partitions, the threat and trust model, and our research objectives. The protection pipeline combines patient-level differential privacy, CAABC-FL, CKKS-protected and authenticated updates, poisoning-aware validation, and governed release. We then measure utility, privacy exposure, encrypted communication, poisoning response, and system correctness. The final stage defines the claim boundary: our evidence applies to the evaluated data, attacks, seeds, and deployment environment, rather than universal or production security.",
);

const after = await slide.export({ format: "png", scale: 2 });
await fs.writeFile(
  path.join(previewDir, "slide-16-after.png"),
  new Uint8Array(await after.arrayBuffer()),
);
const layout = await slide.export({ format: "layout" });
await fs.writeFile(path.join(previewDir, "slide-16-after.layout.json"), await layout.text());
const montage = await presentation.export({ format: "webp", montage: true, scale: 0.5 });
await fs.writeFile(
  path.join(previewDir, "deck-montage.webp"),
  new Uint8Array(await montage.arrayBuffer()),
);

const candidatePath = path.join(
  stagingDir,
  "Board-11_Group-2_CAABC-FL_Final_Defense_Conceptual_Framework_candidate.pptx",
);
await (await PresentationFile.exportPptx(presentation)).save(candidatePath);

const tableOwners = [11, 12, 13, 14, 25, 26, 29, 39];
const result = await finalizePresentation({
  explicitTotalSlideCount: 42,
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
  requiredNativeChartOwnerSlides: [7, 29],
  nativeChartTargetApplication: "powerpoint",
  fontPolicy: {
    basis: "reference",
    families: ["Arial", "Corbel"],
    referencePath: sourcePath,
    referenceSha256: "d815fb5c879d66e343ee0bfc670ca0c376605da99392bdde22123294c8671867",
  },
  verifyArtifactToolImport: true,
  receiptPath: path.join(
    stagingDir,
    "Board-11_Group-2_CAABC-FL_Final_Defense_Conceptual_Framework_v2.validation.json",
  ),
});

console.log(JSON.stringify({ finalPath, slideCount: presentation.slides.items.length, result }, null, 2));
