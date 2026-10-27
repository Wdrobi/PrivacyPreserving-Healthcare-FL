import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = "E:/PrivacyPreserving-Healthcare-FL";
const sourcePath = "C:/Users/HP/Downloads/Board-11_Group-2_CAABC-FL_Final_Defense.pptx";
const finalPath = path.join(
  workspaceDir,
  "output/presentation/Board-11_Group-2_CAABC-FL_Final_Defense_With_Conceptual_Framework_v2.pptx",
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
const researchGapSlide = presentation.slides.getItem(14);
const slide = researchGapSlide.duplicate();
slide.moveTo(15);

const titleShape = slide.shapes.items.find((shape) => shape.name === "Google Shape;211;p28");
if (!titleShape) throw new Error("Duplicated title shape was not found.");
titleShape.text.replace("Research Gap", "Conceptual Framework");
titleShape.name = "chrome-title-16";

slide.shapes.add({
  geometry: "rect",
  name: "conceptual-framework-content-cover",
  position: { left: 65, top: 125, width: 1150, height: 515 },
  fill: "#FFFFFF",
  line: { fill: "none", width: 0 },
});

const FONT = "Arial";
const NAVY = "#17365D";
const GREEN = "#008A46";
const BLUE = "#2E75B6";
const TEAL = "#2F807B";
const PURPLE = "#6B4BB5";
const TEXT = "#263244";
const MUTED = "#5B677A";

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
    verticalAlignment: "middle",
    autoFit: "shrinkText",
    ...style,
  };
  return shape;
}

addText(
  "conceptual-framework-subtitle",
  "Conceptual relationship between the research problem, integrated controls, collaboration process and evaluation outcomes",
  { left: 145, top: 125, width: 990, height: 34 },
  { fontSize: 16, color: MUTED, alignment: "center", italic: true },
);

function addStage({ key, x, title, body, fill, accent }) {
  const box = slide.shapes.add({
    geometry: "roundRect",
    name: `${key}-box`,
    position: { left: x, top: 185, width: 240, height: 198 },
    fill,
    line: { fill: accent, width: 1.7 },
  });
  slide.shapes.add({
    geometry: "rect",
    name: `${key}-accent`,
    position: { left: x, top: 185, width: 240, height: 43 },
    fill: accent,
    line: { fill: "none", width: 0 },
  });
  addText(`${key}-title`, title, { left: x + 10, top: 188, width: 220, height: 36 }, {
    fontSize: 20,
    bold: true,
    color: "#FFFFFF",
    alignment: "center",
  });
  addText(`${key}-body`, body, { left: x + 16, top: 238, width: 208, height: 130 }, {
    fontSize: 15,
    color: TEXT,
    verticalAlignment: "top",
  });
  return box;
}

const context = addStage({
  key: "framework-context",
  x: 75,
  title: "Research context",
  body: "Distributed hospital data\nNon-IID client partitions\nPrivacy and poisoning threats\nHigh encrypted communication cost",
  fill: "#EEF4FA",
  accent: BLUE,
});

const intervention = addStage({
  key: "framework-intervention",
  x: 370,
  title: "Hybrid intervention",
  body: "Record-level differential privacy\nCAABC-FL block compression\nCKKS-protected updates\nTrust and audit governance",
  fill: "#EBF7F2",
  accent: GREEN,
});

const process = addStage({
  key: "framework-process",
  x: 665,
  title: "Collaboration process",
  body: "Protected local training\nAuthenticated update exchange\nVerified homomorphic aggregation\nThreshold-governed model release",
  fill: "#EFF8F7",
  accent: TEAL,
});

const outcomes = addStage({
  key: "framework-outcomes",
  x: 960,
  title: "Measured outcomes",
  body: "Predictive utility\nPrivacy attack exposure\nPoisoning resilience\nSerialized upload and runtime cost",
  fill: "#F3EEF9",
  accent: PURPLE,
});

slide.shapes.connect(context, intervention, {
  kind: "straight",
  fromSide: "right",
  toSide: "left",
  line: { style: "solid", fill: NAVY, width: 2 },
  tail: { type: "triangle", width: "med", length: "med" },
});
slide.shapes.connect(intervention, process, {
  kind: "straight",
  fromSide: "right",
  toSide: "left",
  line: { style: "solid", fill: NAVY, width: 2 },
  tail: { type: "triangle", width: "med", length: "med" },
});
slide.shapes.connect(process, outcomes, {
  kind: "straight",
  fromSide: "right",
  toSide: "left",
  line: { style: "solid", fill: NAVY, width: 2 },
  tail: { type: "triangle", width: "med", length: "med" },
});

slide.shapes.add({
  geometry: "roundRect",
  name: "framework-assumptions-band",
  position: { left: 75, top: 420, width: 1125, height: 118 },
  fill: "#F7F9FC",
  line: { fill: "#AAB6C5", width: 1.2 },
});
addText("framework-assumptions-title", "Cross-cutting threats and trust assumptions", {
  left: 100, top: 429, width: 1075, height: 29,
}, { fontSize: 20, bold: true, color: NAVY, alignment: "center" });
addText(
  "framework-threats",
  "Threats considered\nGradient leakage, membership inference, malicious updates, communication tampering and client dropout",
  { left: 105, top: 463, width: 500, height: 60 },
  { fontSize: 15, color: TEXT, verticalAlignment: "top" },
);
addText(
  "framework-trust-assumptions",
  "Trust assumptions\nAuthenticated institutions, honest-but-curious coordinator, threshold custodians and permissioned audit participants",
  { left: 675, top: 463, width: 500, height: 60 },
  { fontSize: 15, color: TEXT, verticalAlignment: "top" },
);
slide.shapes.add({
  geometry: "rect",
  name: "framework-assumptions-divider",
  position: { left: 638, top: 463, width: 1.5, height: 57 },
  fill: "#CCD5DF",
  line: { fill: "none", width: 0 },
});

slide.shapes.add({
  geometry: "roundRect",
  name: "framework-principle-box",
  position: { left: 180, top: 560, width: 920, height: 62 },
  fill: "#E8F4EE",
  line: { fill: GREEN, width: 1.5 },
});
addText(
  "framework-principle",
  "Core principle: patient records remain inside each institution; only protected updates enter the collaboration, and only a validated global model is released.",
  { left: 205, top: 568, width: 870, height: 46 },
  { fontSize: 17, bold: true, color: NAVY, alignment: "center" },
);

slide.speakerNotes.textFrame.setText(
  "This conceptual framework links the research problem to the proposed intervention and the evaluation plan. Distributed hospital data, non-IID partitions, privacy threats, poisoning risk, and encrypted communication cost define the research context. The hybrid intervention combines record-level differential privacy, CAABC-FL block compression, CKKS-protected updates, and governance controls. These mechanisms support protected local training, authenticated update exchange, verified homomorphic aggregation, and threshold-governed release. The study evaluates predictive utility, privacy exposure, poisoning resilience, communication cost, and runtime overhead under the stated threat and trust assumptions.",
);

for (let index = 0; index < presentation.slides.items.length; index += 1) {
  const current = presentation.slides.getItem(index);
  const pageShape = current.shapes.items.find((shape) => (
    shape.position?.left >= 1175
    && shape.position?.top >= 630
    && shape.position?.height >= 40
  ));
  if (!pageShape) continue;
  const actualNumber = String(index + 1);
  const previousNumber = index + 1 < 16 ? actualNumber : String(index + 1 === 16 ? 15 : index);
  pageShape.text.replace(previousNumber, actualNumber);
}

const candidatePath = path.join(
  stagingDir,
  "Board-11_Group-2_CAABC-FL_Final_Defense_With_Conceptual_Framework_v2_candidate.pptx",
);
await (await PresentationFile.exportPptx(presentation)).save(candidatePath);

const tableOwners = [11, 12, 13, 14, 24, 27, 36];
const result = await finalizePresentation({
  explicitTotalSlideCount: 39,
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
  requiredNativeChartOwnerSlides: [7, 27],
  nativeChartTargetApplication: "powerpoint",
  fontPolicy: {
    basis: "reference",
    families: ["Arial", "Corbel"],
    referencePath: sourcePath,
    referenceSha256: "31f86c6ef0d1c8f46701b4529517b048fc36c3e071cec68a0183951dde7b2d21",
  },
  verifyArtifactToolImport: true,
  receiptPath: path.join(
    stagingDir,
    "Board-11_Group-2_CAABC-FL_Final_Defense_With_Conceptual_Framework_v2.validation.json",
  ),
});

console.log(JSON.stringify({ finalPath, slideCount: presentation.slides.items.length, result }, null, 2));
