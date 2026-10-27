import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = "E:/PrivacyPreserving-Healthcare-FL";
const sourcePath = "C:/Users/HP/Downloads/Board-11_Group-2_CAABC-FL_Final_Defense_With_Experimental_Setup_v2.pptx";
const finalPath = path.join(
  workspaceDir,
  "output/presentation/Board-11_Group-2_CAABC-FL_Final_Defense_With_CAABC_Algorithm_v3.pptx",
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

// Duplicate the local privacy pipeline slide so all manually formatted template
// elements remain unchanged. Insert the algorithm immediately after that slide.
const slide = presentation.slides.getItem(17).duplicate();
slide.moveTo(18);

const FONT = "Arial";
const NAVY = "#062B6F";
const TEXT = "#263244";
const MUTED = "#5B677A";
const GREEN = "#008A46";
const TEAL = "#2E867F";
const BLUE = "#2F75B5";
const PURPLE = "#6F52B5";
const ORANGE = "#B97800";
const CONNECTOR = "#6F849F";

const title = slide.placeholders.getItem("title");
if (!title) throw new Error("Duplicated algorithm slide has no title placeholder.");
title.text.replace("System Approach: Local Privacy Pipeline", "CAABC-FL Algorithm");
title.text.style = {
  typeface: FONT,
  fontSize: 40,
  bold: true,
  color: NAVY,
  alignment: "center",
  verticalAlignment: "middle",
  autoFit: "shrinkText",
};

// Cover only the duplicated body, retaining the university logos, title, footer,
// date, border, and slide number from the reference slide.
slide.shapes.add({
  geometry: "rect",
  name: "caabc-algorithm-body-cover",
  position: { left: 48, top: 105, width: 1184, height: 530 },
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
    fontSize: 16,
    color: TEXT,
    autoFit: "shrinkText",
    ...style,
  };
  return shape;
}

function addBox({ name, text, left, top, width, height, accent, fill = "#FFFFFF", fontSize = 16 }) {
  const shape = slide.shapes.add({
    geometry: "roundRect",
    name,
    position: { left, top, width, height },
    fill,
    line: { fill: accent, width: 1.6 },
  });
  shape.text = text;
  shape.text.style = {
    typeface: FONT,
    fontSize,
    color: TEXT,
    alignment: "center",
    verticalAlignment: "middle",
    autoFit: "shrinkText",
  };
  return shape;
}

function addStepNumber(number, x, accent) {
  const circle = slide.shapes.add({
    geometry: "ellipse",
    name: `caabc-step-${number}-number`,
    position: { left: x + 71, top: 204, width: 42, height: 42 },
    fill: accent,
    line: { fill: accent, width: 1 },
  });
  circle.text = String(number);
  circle.text.style = {
    typeface: FONT,
    fontSize: 20,
    bold: true,
    color: "#FFFFFF",
    alignment: "center",
    verticalAlignment: "middle",
    autoFit: "none",
  };
}

function connect(from, to) {
  const connector = slide.shapes.connect(from, to, {
    kind: "straight",
    fromSide: "right",
    toSide: "left",
    line: { style: "solid", fill: CONNECTOR, width: 1.7 },
    head: { type: "none" },
    tail: { type: "triangle", width: "sm", length: "sm" },
  });
  connector.bringToFront();
}

addText(
  "caabc-algorithm-subtitle",
  "Adaptive common-block compression aligned with CKKS packing",
  { left: 160, top: 112, width: 960, height: 30 },
  { fontSize: 18, italic: true, color: MUTED, alignment: "center", verticalAlignment: "middle" },
);

const inputBar = slide.shapes.add({
  geometry: "roundRect",
  name: "caabc-algorithm-inputs",
  position: { left: 122, top: 151, width: 1036, height: 43 },
  fill: "#F2F6FA",
  line: { fill: "#AFC1D5", width: 1.1 },
});
inputBar.text = "Inputs: privatized client update Δ̃ₖ,ₜ   residual rₖ,ₜ   block size B = 256   chunk budget c = 2   refresh interval τ = 5";
inputBar.text.style = {
  typeface: FONT,
  fontSize: 16,
  bold: true,
  color: NAVY,
  alignment: "center",
  verticalAlignment: "middle",
  autoFit: "shrinkText",
};

const x = [92, 322, 552, 782, 1012];
const accents = [PURPLE, BLUE, ORANGE, GREEN, TEAL];
const fills = ["#F5F0FC", "#EEF5FC", "#FFF6E4", "#ECF7F0", "#EAF6F5"];
const labels = [
  "PRIVATE UPDATE + RESIDUAL\n\nuₖ,ₜ = Δ̃ₖ,ₜ + rₖ,ₜ\n\nCarry omitted information into the current round",
  "BLOCK SCORING\n\nPartition uₖ,ₜ into contiguous 256-coordinate blocks\n\nScore block energy from privatized updates",
  "COMMON SUPPORT\n\nSelect Sₜ from aggregate block scores\n\nRefresh every five rounds and fit within two CKKS chunks",
  "PROJECT + REMEMBER\n\npₖ,ₜ = Pₛₜ(uₖ,ₜ)\nrₖ,ₜ₊₁ = uₖ,ₜ − Pₛₜᵀpₖ,ₜ",
  "PACK + PROTECT\n\nPack pₖ,ₜ into aligned slots\nEncrypt, sign and homomorphically aggregate",
];

const steps = labels.map((label, index) => {
  const box = addBox({
    name: `caabc-step-${index + 1}`,
    text: label,
    left: x[index],
    top: 228,
    width: 184,
    height: 225,
    accent: accents[index],
    fill: fills[index],
    fontSize: index === 3 ? 15.5 : 15,
  });
  addStepNumber(index + 1, x[index], accents[index]);
  return box;
});

for (let i = 0; i < steps.length - 1; i += 1) connect(steps[i], steps[i + 1]);

const propertyBar = slide.shapes.add({
  geometry: "roundRect",
  name: "caabc-algorithm-property",
  position: { left: 112, top: 482, width: 1056, height: 62 },
  fill: "#EEF7F4",
  line: { fill: GREEN, width: 1.2 },
});
propertyBar.text = "Algorithmic contribution: one public support keeps every client ciphertext aligned, so logical block sparsity becomes a real reduction in serialized encrypted traffic.";
propertyBar.text.style = {
  typeface: FONT,
  fontSize: 17,
  bold: true,
  color: "#1F5B50",
  alignment: "center",
  verticalAlignment: "middle",
  autoFit: "shrinkText",
};

const outputBar = slide.shapes.add({
  geometry: "roundRect",
  name: "caabc-algorithm-output",
  position: { left: 236, top: 562, width: 808, height: 48 },
  fill: "#F4F6FA",
  line: { fill: NAVY, width: 1.1 },
});
outputBar.text = "Output: two aligned CKKS ciphertext chunks, an updated residual, and an aggregation-compatible protected update";
outputBar.text.style = {
  typeface: FONT,
  fontSize: 16.5,
  bold: true,
  color: NAVY,
  alignment: "center",
  verticalAlignment: "middle",
  autoFit: "shrinkText",
};

// Reassert logos so the duplicated slide remains stable across PowerPoint readers.
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
  "This slide explains our main algorithmic contribution, CAABC-FL. Each hospital first adds the previous compression residual to its patient-level differentially private update. The method divides that effective update into contiguous 256-coordinate blocks and scores block energy only after privatization. Every fifth round, the hospitals derive one common support from aggregate block scores, subject to a two-ciphertext packing budget. Each hospital projects onto the same support and retains omitted information as the next residual. The selected blocks occupy aligned CKKS slots, so the coordinator can add ciphertexts without learning client-specific sparse indices. This shared support is the central novelty because it converts logical sparsity into measured encrypted-wire reduction. Formal privacy still comes from the differential privacy accountant, not from compression.",
);

// Renumber this slide and all following slides. The page-number shape sits in the
// lower-right corner in the supplied template.
for (let index = 0; index < presentation.slides.items.length; index += 1) {
  const current = presentation.slides.getItem(index);
  const pageShape = current.shapes.items.find((shape) => (
    shape.position?.left >= 1175
    && shape.position?.top >= 630
    && shape.position?.height >= 40
  ));
  if (!pageShape) continue;
  const expected = String(index + 1);
  pageShape.text = expected;
  pageShape.text.style = {
    typeface: FONT,
    fontSize: 30,
    color: NAVY,
    alignment: "center",
    verticalAlignment: "middle",
    autoFit: "shrinkText",
  };
}

const candidatePath = path.join(
  stagingDir,
  "Board-11_Group-2_CAABC-FL_Final_Defense_With_CAABC_Algorithm_candidate.pptx",
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
    referenceSha256: "d8b615e0e7b844a1b797fb9460d0a61ab3fc43757e611acee5cabeab1ac5b587",
  },
  verifyArtifactToolImport: true,
  receiptPath: path.join(
    stagingDir,
    "Board-11_Group-2_CAABC-FL_Final_Defense_With_CAABC_Algorithm_v3.validation.json",
  ),
});

console.log(JSON.stringify({ finalPath, slideCount: presentation.slides.items.length, result }, null, 2));

