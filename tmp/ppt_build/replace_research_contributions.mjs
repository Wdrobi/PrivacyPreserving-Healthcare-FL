import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = "E:/PrivacyPreserving-Healthcare-FL";
const sourcePath = path.join(
  workspaceDir,
  "output/presentation/Board-11_Group-2_CAABC-FL_Final_Defense_Conceptual_Framework_v2.pptx",
);
const finalPath = path.join(
  workspaceDir,
  "output/presentation/Board-11_Group-2_CAABC-FL_Final_Defense_Contributions_v3.pptx",
);
const stagingDir = path.join(workspaceDir, ".codex-finalizer");
const previewDir = path.join(workspaceDir, "tmp/ppt_build/contribution_after");
const skillDir = "C:/Users/HP/.codex/plugins/cache/openai-primary-runtime/presentations/26.909.12148/skills/presentations";
const runtimePython = "C:/Users/HP/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe";

const { finalizePresentation } = await import(
  pathToFileURL(path.join(skillDir, "container_tools/artifact_tool_utils.mjs")).href,
);

await fs.mkdir(stagingDir, { recursive: true });
await fs.mkdir(previewDir, { recursive: true });
await fs.mkdir(path.dirname(finalPath), { recursive: true });

const presentation = await PresentationFile.importPptx(await FileBlob.load(sourcePath));
const slide = presentation.resolve("sl/nax4b2dk");
if (!slide) throw new Error("Research Contributions slide not found.");

const FONT = "Arial";
const NAVY = "#062B6F";
const GREEN = "#008A46";
const BLUE = "#00A6DF";
const TEXT = "#263244";
const MUTED = "#5D6878";
const PALE_BLUE = "#EAF7FC";
const RULE = "#D9E2EC";

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

function addRule(name, left, top, width, fill) {
  slide.shapes.add({
    geometry: "rect",
    name,
    position: { left, top, width, height: 2.3 },
    fill,
    line: { fill: "none", width: 0 },
  });
}

function addContribution({ number, title, body, left, top, width, bodyHeight, accent }) {
  addText(
    `contribution-${number}-number`,
    number,
    { left, top, width: 44, height: 30 },
    { fontSize: 14.5, bold: true, color: accent, alignment: "left" },
  );
  addText(
    `contribution-${number}-title`,
    title,
    { left: left + 48, top: top - 2, width: width - 48, height: 35 },
    { fontSize: 21, bold: true, color: accent, alignment: "left" },
  );
  addRule(`contribution-${number}-rule`, left, top + 36, width, accent);
  addText(
    `contribution-${number}-body`,
    body,
    { left, top: top + 46, width, height: bodyHeight },
    { fontSize: 16.5, color: TEXT, alignment: "left", verticalAlignment: "top" },
  );
}

// Preserve the template title, logos, date, page number and bottom title.
slide.shapes.add({
  geometry: "rect",
  name: "research-contributions-replacement-cover",
  position: { left: 55, top: 120, width: 1170, height: 520 },
  fill: "#FFFFFF",
  line: { fill: "none", width: 0 },
});

addContribution({
  number: "01",
  title: "Theoretical contribution",
  body: "Defines collaboration through four interacting properties: released-model privacy, update confidentiality, encrypted communication efficiency, and accountable integrity.",
  left: 85,
  top: 142,
  width: 500,
  bodyHeight: 70,
  accent: GREEN,
});

addContribution({
  number: "02",
  title: "Algorithmic contribution",
  body: "CAABC-FL combines encrypted aggregate block scoring, shared CKKS-aligned support, periodic refresh, and residual error feedback.",
  left: 85,
  top: 278,
  width: 500,
  bodyHeight: 70,
  accent: NAVY,
});

addContribution({
  number: "03",
  title: "Practical contribution",
  body: "Implements a multi-service system with signed artifacts, independent aggregate checks, governed release and inference, rollback, and three external audit witnesses.",
  left: 85,
  top: 414,
  width: 500,
  bodyHeight: 82,
  accent: GREEN,
});

addContribution({
  number: "04",
  title: "Methodological contribution",
  body: "Uses a frozen paired protocol to measure utility, privacy attacks, one-round and longitudinal poisoning, ciphertext bytes, correctness, timing, and statistical uncertainty.",
  left: 660,
  top: 142,
  width: 500,
  bodyHeight: 90,
  accent: NAVY,
});

addText(
  "contribution-05-number",
  "05",
  { left: 660, top: 316, width: 44, height: 30 },
  { fontSize: 14.5, bold: true, color: BLUE, alignment: "left" },
);
addText(
  "contribution-05-title",
  "Empirical contribution",
  { left: 708, top: 314, width: 452, height: 35 },
  { fontSize: 21, bold: true, color: BLUE, alignment: "left" },
);
addRule("contribution-05-rule", 660, 352, 500, BLUE);

slide.shapes.add({
  geometry: "roundRect",
  name: "empirical-result-highlight",
  position: { left: 660, top: 371, width: 500, height: 88 },
  fill: PALE_BLUE,
  line: { fill: "#8CCFE7", width: 1.2 },
});
addText(
  "empirical-56-percent",
  "56.0%",
  { left: 680, top: 383, width: 155, height: 52 },
  { fontSize: 33, bold: true, color: NAVY, alignment: "center" },
);
addText(
  "empirical-reduction-label",
  "lower encrypted upload",
  { left: 845, top: 387, width: 285, height: 45 },
  { fontSize: 18.5, bold: true, color: NAVY, alignment: "left" },
);
addText(
  "empirical-result-body",
  "CAABC-FL met the registered AUROC non-inferiority criterion. AUPRC and operating-point trade-offs remain visible.",
  { left: 660, top: 472, width: 500, height: 68 },
  { fontSize: 16.5, color: TEXT, alignment: "left", verticalAlignment: "top" },
);

slide.shapes.add({
  geometry: "rect",
  name: "claim-boundary-note-background",
  position: { left: 85, top: 567, width: 1075, height: 48 },
  fill: "#F6F8FA",
  line: { fill: RULE, width: 1 },
});
addText(
  "claim-boundary-note",
  "Evidence boundary: claims apply to the evaluated dataset, attacks, seeds, trust assumptions, and deployment environment.",
  { left: 105, top: 574, width: 1035, height: 34 },
  { fontSize: 14.3, italic: true, color: MUTED, alignment: "center" },
);

slide.speakerNotes.textFrame.setText(
  "Our thesis makes five contributions. First, the theoretical model treats privacy, confidentiality, communication efficiency, and integrity as interacting properties, which exposes conflicts between controls. Second, CAABC-FL aligns adaptive common-block selection with CKKS packing and residual feedback. Third, we implemented a governed multi-service system with independent verification and external audit witnesses. Fourth, the frozen paired protocol evaluates utility, privacy, poisoning, and system cost under the same conditions. Finally, CAABC-FL reduced encrypted upload by 56 percent while meeting the registered AUROC non-inferiority criterion. We also report the weaker AUPRC and operating-point results, so the claim remains within the evidence.",
);

const after = await slide.export({ format: "png", scale: 2 });
await fs.writeFile(
  path.join(previewDir, "slide-33-after.png"),
  new Uint8Array(await after.arrayBuffer()),
);
const layout = await slide.export({ format: "layout" });
await fs.writeFile(path.join(previewDir, "slide-33-after.layout.json"), await layout.text());

const candidatePath = path.join(
  stagingDir,
  "Board-11_Group-2_CAABC-FL_Final_Defense_Contributions_v3_candidate.pptx",
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
    referenceSha256: "0d76301c5594ada919a78faa90d0f225d895887d92c39ab9e884ec58bb73e954",
  },
  verifyArtifactToolImport: true,
  receiptPath: path.join(
    stagingDir,
    "Board-11_Group-2_CAABC-FL_Final_Defense_Contributions_v3.validation.json",
  ),
});

console.log(JSON.stringify({ finalPath, slideCount: presentation.slides.items.length, result }, null, 2));
