import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = "E:/PrivacyPreserving-Healthcare-FL";
const sourcePath = path.join(
  workspaceDir,
  "output/presentation/CAABC-FL_Final_Defense_25_September_2026_System_Approach_Split_v3.pptx",
);
const finalPath = path.join(
  workspaceDir,
  "output/presentation/CAABC-FL_Final_Defense_25_September_2026_System_Approach_Professional_v2.pptx",
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
const localSlide = presentation.slides.getItem(16);
const releaseSlide = presentation.slides.getItem(17);

const FONT = "Arial";
const NAVY = "#062B6F";
const TEXT = "#1F2937";
const MUTED = "#52606D";
const CONNECTOR = "#7A8DA5";

const PALETTE = {
  governance: { accent: "#2F6690", fill: "#EEF4FB" },
  data: { accent: "#3C78A8", fill: "#F1F6FB" },
  crypto: { accent: "#2F7F77", fill: "#ECF7F5" },
  privacy: { accent: "#6B4FB3", fill: "#F3EFFB" },
  trust: { accent: "#A66F0A", fill: "#FFF6E3" },
  secure: { accent: "#2E7D4F", fill: "#EDF7F0" },
  inference: { accent: "#287D78", fill: "#ECF7F6" },
  reject: { accent: "#C94B4B", fill: "#FDEEEE" },
};

function addCover(slide, name) {
  slide.shapes.add({
    geometry: "rect",
    name,
    position: { left: 42, top: 112, width: 1196, height: 535 },
    fill: "#FFFFFF",
    line: { fill: "none", width: 0 },
  });
}

function setTitle(slide, text) {
  const title = slide.placeholders.getItem("title");
  if (!title) throw new Error(`Missing title placeholder: ${text}`);
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

function addTextbox(slide, name, text, position, style = {}) {
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

function addLane(slide, { id, title, y, h, accent, fill }) {
  slide.shapes.add({
    geometry: "roundRect",
    name: `${id}-lane-background`,
    position: { left: 86, top: y, width: 1110, height: h },
    fill,
    line: { fill: "#D8E0E8", width: 1 },
  });
  const band = slide.shapes.add({
    geometry: "roundRect",
    name: `${id}-lane-label`,
    position: { left: 96, top: y + 10, width: 145, height: h - 20 },
    fill: accent,
    line: { fill: accent, width: 1 },
  });
  band.text = `${id}\n${title}`;
  band.text.style = {
    typeface: FONT,
    fontSize: 15,
    bold: true,
    color: "#FFFFFF",
    alignment: "center",
    verticalAlignment: "middle",
    autoFit: "shrinkText",
  };
  return band;
}

function addBox(slide, { name, text, x, y, w, h, accent, fill, fontSize = 16, bold = false, geometry = "roundRect" }) {
  const shape = slide.shapes.add({
    geometry,
    name,
    position: { left: x, top: y, width: w, height: h },
    fill,
    line: { fill: accent, width: 1.4 },
  });
  shape.text = text;
  shape.text.style = {
    typeface: FONT,
    fontSize,
    bold,
    color: TEXT,
    alignment: "center",
    verticalAlignment: "middle",
    autoFit: "shrinkText",
  };
  return shape;
}

function connect(slide, from, to, options = {}) {
  const connector = slide.shapes.connect(from, to, {
    kind: options.kind ?? "straight",
    fromSide: options.fromSide ?? "right",
    toSide: options.toSide ?? "left",
    line: { style: options.style ?? "solid", fill: options.color ?? CONNECTOR, width: options.width ?? 1.7 },
    head: { type: "none" },
    tail: { type: "triangle", width: "sm", length: "sm" },
  });
  connector.bringToFront();
  return connector;
}

function connectRow(slide, shapes) {
  for (let i = 0; i < shapes.length - 1; i += 1) connect(slide, shapes[i], shapes[i + 1]);
}

function addOutcomeNote(slide, text, accent, fill) {
  const note = slide.shapes.add({
    geometry: "roundRect",
    name: "diagram-outcome-note",
    position: { left: 315, top: 597, width: 650, height: 36 },
    fill,
    line: { fill: accent, width: 1.2 },
  });
  note.text = text;
  note.text.style = {
    typeface: FONT,
    fontSize: 17,
    bold: true,
    color: accent,
    alignment: "center",
    verticalAlignment: "middle",
    autoFit: "shrinkText",
  };
  return note;
}

// Slide 17: policy, local data, cryptographic setup, and protected client update.
addCover(localSlide, "native-local-pipeline-cover");
setTitle(localSlide, "System Approach: Local Privacy Pipeline");

const system = addBox(localSlide, {
  name: "local-system-header",
  text: "Secure Multi-Institutional Healthcare Federated Learning",
  x: 315, y: 119, w: 650, h: 38,
  accent: PALETTE.governance.accent,
  fill: "#F4F7FB",
  fontSize: 18,
  bold: true,
});

const localLanes = [
  { id: "L0", title: "Governance", y: 170, h: 92, ...PALETTE.governance },
  { id: "L1", title: "Local data", y: 272, h: 92, ...PALETTE.data },
  { id: "L2", title: "Key setup", y: 374, h: 92, ...PALETTE.crypto },
  { id: "L3", title: "Private training", y: 476, h: 108, ...PALETTE.privacy },
];
for (const lane of localLanes) addLane(localSlide, lane);

const l0 = [
  addBox(localSlide, { name: "l0-ca", text: "Consortium CA\nidentity and roles", x: 285, y: 190, w: 205, h: 53, ...PALETTE.governance }),
  addBox(localSlide, { name: "l0-consent", text: "Consent registry\nscope and revocation", x: 550, y: 190, w: 205, h: 53, ...PALETTE.governance }),
  addBox(localSlide, { name: "l0-policy", text: "Governance policy\naccess and incident rules", x: 815, y: 190, w: 230, h: 53, ...PALETTE.governance }),
];
connectRow(localSlide, l0);

const l1 = [
  addBox(localSlide, { name: "l1-hospitals", text: "Hospitals\nA, B, C, ... N", x: 268, y: 292, w: 165, h: 53, ...PALETTE.data }),
  addBox(localSlide, { name: "l1-check", text: "Consent and\npurpose check", x: 475, y: 292, w: 175, h: 53, ...PALETTE.data }),
  addBox(localSlide, { name: "l1-preprocess", text: "Preprocess and\nnormalize features", x: 692, y: 292, w: 190, h: 53, ...PALETTE.data }),
  addBox(localSlide, { name: "l1-onsite", text: "Local dataset\nremains at hospital", x: 924, y: 292, w: 190, h: 53, ...PALETTE.data }),
];
connectRow(localSlide, l1);

const l2 = [
  addBox(localSlide, { name: "l2-rotate", text: "Key rotation and\nrevocation", x: 268, y: 394, w: 175, h: 53, ...PALETTE.crypto }),
  addBox(localSlide, { name: "l2-keygen", text: "Distributed\nkey generation", x: 486, y: 394, w: 175, h: 53, ...PALETTE.crypto }),
  addBox(localSlide, { name: "l2-pubkey", text: "Collective CKKS\npublic key", x: 704, y: 394, w: 180, h: 53, ...PALETTE.crypto }),
  addBox(localSlide, { name: "l2-shares", text: "Threshold shares\nprotected by custodians", x: 927, y: 394, w: 205, h: 53, ...PALETTE.crypto }),
];
connectRow(localSlide, l2);

const l3 = [
  addBox(localSlide, { name: "l3-train", text: "Local model\ntraining", x: 254, y: 505, w: 145, h: 55, ...PALETTE.privacy }),
  addBox(localSlide, { name: "l3-clip", text: "Clip per-record\ngradients", x: 422, y: 505, w: 145, h: 55, ...PALETTE.privacy }),
  addBox(localSlide, { name: "l3-noise", text: "Add calibrated\nDP noise", x: 590, y: 505, w: 145, h: 55, ...PALETTE.privacy }),
  addBox(localSlide, { name: "l3-caabc", text: "CAABC-FL block\ncompression", x: 758, y: 505, w: 155, h: 55, ...PALETTE.privacy, bold: true }),
  addBox(localSlide, { name: "l3-encrypt", text: "CKKS encrypt\nand sign update", x: 936, y: 505, w: 165, h: 55, accent: PALETTE.crypto.accent, fill: PALETTE.crypto.fill }),
];
connectRow(localSlide, l3);

connect(localSlide, system, l0[1], { kind: "elbow", fromSide: "bottom", toSide: "top" });
connect(localSlide, l0[1], l1[1], { kind: "elbow", fromSide: "bottom", toSide: "top" });
connect(localSlide, l1[3], l2[2], { kind: "elbow", fromSide: "bottom", toSide: "top" });
connect(localSlide, l2[3], l3[4], { kind: "elbow", fromSide: "bottom", toSide: "top" });
addOutcomeNote(localSlide, "Output: encrypted, compressed and signed client update", PALETTE.crypto.accent, PALETTE.crypto.fill);

localSlide.speakerNotes.textFrame.setText(
  "This slide shows how each institution constructs a protected model update. Governance establishes identity, consent, and policy. Patient records remain inside each hospital during preprocessing and training. The consortium creates a collective CKKS public key while independent custodians protect threshold shares. Each hospital clips per-record gradients, adds calibrated differential-privacy noise, applies CAABC-FL block compression, encrypts the result, and signs the submission.",
);

// Slide 18: authenticated transport, encrypted aggregation, release, and inference.
addCover(releaseSlide, "native-release-pipeline-cover");
setTitle(releaseSlide, "System Approach: Trust and Model Release");

const releaseLanes = [
  { id: "L4", title: "Trust and transport", y: 140, h: 94, ...PALETTE.trust },
  { id: "L5", title: "Secure aggregation", y: 244, h: 140, ...PALETTE.secure },
  { id: "L6", title: "Verified release", y: 394, h: 92, ...PALETTE.secure },
  { id: "L7", title: "Private inference", y: 496, h: 92, ...PALETTE.inference },
];
for (const lane of releaseLanes) addLane(releaseSlide, lane);

const l4 = [
  addBox(releaseSlide, { name: "l4-mtls", text: "Mutual TLS\nsecure channel", x: 260, y: 160, w: 170, h: 54, ...PALETTE.trust }),
  addBox(releaseSlide, { name: "l4-verify", text: "Verify identity, signature\nand round freshness", x: 475, y: 160, w: 195, h: 54, ...PALETTE.trust }),
  addBox(releaseSlide, { name: "l4-admit", text: "Admission policy\nand reputation check", x: 715, y: 160, w: 190, h: 54, ...PALETTE.trust }),
  addBox(releaseSlide, { name: "l4-ledger", text: "Ciphertext off-chain\nhash and status on ledger", x: 950, y: 160, w: 205, h: 54, ...PALETTE.trust }),
];
connectRow(releaseSlide, l4);

const l5 = [
  addBox(releaseSlide, { name: "l5-quorum", text: "Quorum and\ndropout handling", x: 246, y: 286, w: 145, h: 56, ...PALETTE.secure }),
  addBox(releaseSlide, { name: "l5-fedavg", text: "Reputation-weighted\nhomomorphic FedAvg", x: 420, y: 286, w: 170, h: 56, ...PALETTE.secure }),
  addBox(releaseSlide, { name: "l5-decrypt", text: "Threshold decrypt\naggregate only", x: 619, y: 286, w: 155, h: 56, accent: PALETTE.crypto.accent, fill: PALETTE.crypto.fill }),
  addBox(releaseSlide, { name: "l5-validate", text: "Validate utility, drift\nand anomaly checks", x: 803, y: 286, w: 160, h: 56, ...PALETTE.secure }),
  addBox(releaseSlide, { name: "l5-decision", text: "Pass?", x: 982, y: 279, w: 88, h: 70, ...PALETTE.secure, geometry: "diamond", bold: true, fontSize: 14 }),
];
connectRow(releaseSlide, l5);
const accept = addBox(releaseSlide, { name: "l5-accept", text: "Accept model", x: 1090, y: 257, w: 95, h: 42, ...PALETTE.secure, fontSize: 14, bold: true });
const reject = addBox(releaseSlide, { name: "l5-reject", text: "Rollback and\nquarantine", x: 1090, y: 326, w: 95, h: 44, ...PALETTE.reject, fontSize: 14, bold: true });
connect(releaseSlide, l5[4], accept, { kind: "elbow", fromSide: "right", toSide: "left", color: PALETTE.secure.accent });
connect(releaseSlide, l5[4], reject, { kind: "elbow", fromSide: "bottom", toSide: "left", color: PALETTE.reject.accent });
addTextbox(releaseSlide, "accept-label", "YES", { left: 1067, top: 257, width: 34, height: 20 }, { fontSize: 11, bold: true, color: PALETTE.secure.accent });
addTextbox(releaseSlide, "reject-label", "NO", { left: 1059, top: 342, width: 30, height: 20 }, { fontSize: 11, bold: true, color: PALETTE.reject.accent });

const l6 = [
  addBox(releaseSlide, { name: "l6-record", text: "Record global-model\nhash", x: 277, y: 414, w: 175, h: 52, ...PALETTE.secure }),
  addBox(releaseSlide, { name: "l6-broadcast", text: "Signed secure\nbroadcast", x: 502, y: 414, w: 175, h: 52, ...PALETTE.secure }),
  addBox(releaseSlide, { name: "l6-verify", text: "Hospitals verify\nversion and hash", x: 727, y: 414, w: 175, h: 52, ...PALETTE.secure }),
  addBox(releaseSlide, { name: "l6-next", text: "Begin next\nFL round", x: 952, y: 414, w: 155, h: 52, ...PALETTE.secure }),
];
connectRow(releaseSlide, l6);

const l7 = [
  addBox(releaseSlide, { name: "l7-auth", text: "Authenticate\nrequest", x: 246, y: 516, w: 145, h: 52, ...PALETTE.inference }),
  addBox(releaseSlide, { name: "l7-consent", text: "Consent and\nauthorization", x: 418, y: 516, w: 150, h: 52, ...PALETTE.inference }),
  addBox(releaseSlide, { name: "l7-infer", text: "Encrypted or\nconfidential inference", x: 595, y: 516, w: 170, h: 52, ...PALETTE.inference }),
  addBox(releaseSlide, { name: "l7-decrypt", text: "Controlled result\ndecryption", x: 792, y: 516, w: 155, h: 52, ...PALETTE.inference }),
  addBox(releaseSlide, { name: "l7-output", text: "Minimized, rate-limited\nand audited output", x: 974, y: 516, w: 185, h: 52, ...PALETTE.inference }),
];
connectRow(releaseSlide, l7);

connect(releaseSlide, l4[3], l5[0], { kind: "elbow", fromSide: "bottom", toSide: "top" });
connect(releaseSlide, accept, l6[0], { kind: "elbow", fromSide: "bottom", toSide: "top", color: PALETTE.secure.accent });
connect(releaseSlide, l6[3], l7[0], { kind: "elbow", fromSide: "bottom", toSide: "top", style: "dashed", color: PALETTE.inference.accent });

addTextbox(
  releaseSlide,
  "release-boundary-note",
  "Only the validated aggregate can become the global model. The audit ledger stores evidence, not model ciphertexts.",
  { left: 230, top: 598, width: 820, height: 36 },
  { fontSize: 16, italic: true, color: MUTED },
);

releaseSlide.speakerNotes.textFrame.setText(
  "This slide shows how the framework transports, aggregates, validates, and releases a model. Mutual TLS and signed round metadata authenticate every submission. The permissioned ledger stores hashes and status, while model ciphertexts remain off-chain. The coordinator performs reputation-weighted homomorphic aggregation and custodians decrypt only the aggregate. Validation either accepts the candidate model or triggers rollback and quarantine. Hospitals verify the signed model hash before starting the next round. Clinical inference follows the same authorization and controlled-decryption policy.",
);

const candidatePath = path.join(
  stagingDir,
  "CAABC-FL_Final_Defense_25_September_2026_System_Approach_Professional_candidate.pptx",
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
    referenceSha256: "fb628877d932a42ef4935df9736b6c8491520ba09ef4b99c27a4a373ec07584a",
  },
  verifyArtifactToolImport: true,
  receiptPath: path.join(
    stagingDir,
    "CAABC-FL_Final_Defense_25_September_2026_System_Approach_Professional_v2.validation.json",
  ),
});

console.log(JSON.stringify({ finalPath, slideCount: presentation.slides.items.length, result }, null, 2));
