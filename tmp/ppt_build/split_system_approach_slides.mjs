import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = "E:/PrivacyPreserving-Healthcare-FL";
const sourcePath = path.join(
  workspaceDir,
  "output/presentation/CAABC-FL_Final_Defense_25_September_2026_Related_Studies_Comparison_v3.pptx",
);
const finalPath = path.join(
  workspaceDir,
  "output/presentation/CAABC-FL_Final_Defense_25_September_2026_System_Approach_Split_v3.pptx",
);
const stagingDir = path.join(workspaceDir, ".codex-finalizer");
const skillDir = "C:/Users/HP/.codex/plugins/cache/openai-primary-runtime/presentations/26.909.12148/skills/presentations";
const runtimePython = "C:/Users/HP/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe";
const architectureTopPath = path.join(workspaceDir, "tmp/ppt_assets/architecture_l0_l3.png");
const architectureBottomPath = path.join(workspaceDir, "tmp/ppt_assets/architecture_l4_l7.png");

const { finalizePresentation } = await import(
  pathToFileURL(path.join(skillDir, "container_tools/artifact_tool_utils.mjs")).href,
);

await fs.mkdir(stagingDir, { recursive: true });
await fs.mkdir(path.dirname(finalPath), { recursive: true });

const presentation = await PresentationFile.importPptx(await FileBlob.load(sourcePath));
const firstSlide = presentation.slides.getItem(16);
const secondSlide = firstSlide.duplicate();
secondSlide.moveTo(17);

const FONT = "Arial";
const NAVY = "#062B6F";
const BODY = "#1F2937";
const architectureTopBytes = new Uint8Array(await fs.readFile(architectureTopPath));
const architectureBottomBytes = new Uint8Array(await fs.readFile(architectureBottomPath));

function addCover(slide, name) {
  slide.shapes.add({
    geometry: "rect",
    name,
    position: { left: 42, top: 112, width: 1196, height: 535 },
    fill: "#FFFFFF",
    line: { fill: "none", width: 0 },
  });
}

function styleTitle(slide, text) {
  const title = slide.placeholders.getItem("title");
  if (!title) throw new Error(`Missing title placeholder for ${text}`);
  title.text = text;
  title.text.style = {
    typeface: FONT,
    fontSize: 36,
    bold: true,
    color: NAVY,
    alignment: "center",
    verticalAlignment: "middle",
    autoFit: "shrinkText",
  };
}

function addText(slide, name, text, position, style = {}) {
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
    fontSize: 18,
    color: BODY,
    alignment: "center",
    verticalAlignment: "middle",
    autoFit: "shrinkText",
    ...style,
  };
  return shape;
}

function addArchitectureImage(slide, name, bytes, position, alt) {
  return slide.images.add({
    blob: bytes,
    contentType: "image/png",
    alt,
    fit: "contain",
    position,
    name,
  });
}

async function addImage(slide, filePath, position, alt) {
  const bytes = new Uint8Array(await fs.readFile(filePath));
  return slide.images.add({
    blob: bytes,
    contentType: filePath.toLowerCase().endsWith(".png") ? "image/png" : "image/jpeg",
    alt,
    fit: "contain",
    position,
  });
}

function restoreDuplicatedSlideChrome(slide) {
  slide.shapes.add({
    geometry: "rect",
    name: "system-split-border",
    position: { left: 30, top: 31, width: 1240, height: 664 },
    fill: "none",
    line: { fill: "#222222", width: 1.2 },
  });
  slide.shapes.add({
    geometry: "rect",
    name: "system-split-footer-rule",
    position: { left: 45, top: 665, width: 1190, height: 1 },
    fill: "#C8D9A5",
    line: { fill: "none", width: 0 },
  });
}

addCover(firstSlide, "system-approach-top-cover");
styleTitle(firstSlide, "System Approach: Local Privacy Pipeline");
addArchitectureImage(
  firstSlide,
  "system-approach-layers-l0-l3",
  architectureTopBytes,
  { left: 70, top: 130, width: 1140, height: 412 },
  "CAABC-FL architecture layers L0 to L3: governance, local data, distributed cryptography, and privacy-safe training",
);
addText(
  firstSlide,
  "system-approach-caption-part-1",
  "Fig. 1(a). Governance, local data handling, distributed CKKS setup, DP training, CAABC-FL compression, encryption, and signed submission.",
  { left: 115, top: 558, width: 1050, height: 58 },
  { fontSize: 19, italic: true },
);
firstSlide.speakerNotes.textFrame.setText(
  "Part one covers layers L0 to L3. The consortium defines identity, consent, and governance policies before each hospital prepares local data. Hospitals jointly establish the CKKS public key and threshold key shares. Each participant then trains locally, clips per-record gradients, applies calibrated differential-privacy noise, compresses aligned parameter blocks with CAABC-FL, encrypts the update, and signs the round submission.",
);

addCover(secondSlide, "system-approach-bottom-cover");
styleTitle(secondSlide, "System Approach: Trust and Model Release");
addArchitectureImage(
  secondSlide,
  "system-approach-layers-l4-l7",
  architectureBottomBytes,
  { left: 70, top: 134, width: 1140, height: 405 },
  "CAABC-FL architecture layers L4 to L7: secure communication, poisoning-resilient aggregation, verified distribution, and private inference",
);
addText(
  secondSlide,
  "system-approach-caption-part-2",
  "Fig. 1(b). Authenticated transport, trust policy, encrypted aggregation, validation, threshold release, verified distribution, and private inference.",
  { left: 115, top: 554, width: 1050, height: 60 },
  { fontSize: 19, italic: true },
);
restoreDuplicatedSlideChrome(secondSlide);
await addImage(
  secondSlide,
  path.join(workspaceDir, "tmp/ppt_assets/image1.jpg"),
  { left: 38, top: 39, width: 72, height: 72 },
  "Computer Science and Engineering emblem",
);
await addImage(
  secondSlide,
  path.join(workspaceDir, "tmp/ppt_assets/image2.png"),
  { left: 1041, top: 26, width: 204, height: 85 },
  "Green University of Bangladesh logo",
);
addText(
  secondSlide,
  "system-split-visible-date",
  "25 September 2026",
  { left: 49, top: 670, width: 190, height: 22 },
  { fontSize: 12, color: NAVY, alignment: "left" },
);
secondSlide.speakerNotes.textFrame.setText(
  "Part two covers layers L4 to L7. The framework authenticates each encrypted update, checks freshness and admission policy, and records only hashes and status on the permissioned ledger. The coordinator aggregates ciphertexts, applies reputation-aware weighting, and requests threshold decryption of the aggregate only. Validation either accepts the candidate model or triggers rollback and quarantine. Hospitals verify the released model hash before the next round, while inference follows the same consent and controlled-decryption policy.",
);

const pageSnapshot = await presentation.inspect({
  kind: "textbox",
  include: "id,slide,text,bbox",
  maxChars: 200000,
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
  "CAABC-FL_Final_Defense_25_September_2026_System_Approach_Split_candidate.pptx",
);
await (await PresentationFile.exportPptx(presentation)).save(candidatePath);

const tableOwners = [11, 12, 13, 14, 23, 26, 35];
const result = await finalizePresentation({
  explicitTotalSlideCount: 38,
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
  requiredNativeChartOwnerSlides: [7, 26],
  nativeChartTargetApplication: "powerpoint",
  fontPolicy: {
    basis: "reference",
    families: ["Arial", "Corbel"],
    referencePath: sourcePath,
    referenceSha256: "188eef837fbd46ce34e6056f473f14b25c3e8e4cff877103712216aabdc80799",
  },
  verifyArtifactToolImport: true,
  receiptPath: path.join(
    stagingDir,
    "CAABC-FL_Final_Defense_25_September_2026_System_Approach_Split_v3.validation.json",
  ),
});

console.log(JSON.stringify({ finalPath, slideCount: presentation.slides.items.length, result }, null, 2));
