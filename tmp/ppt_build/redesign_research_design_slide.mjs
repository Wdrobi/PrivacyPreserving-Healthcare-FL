import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = "E:/PrivacyPreserving-Healthcare-FL";
const sourcePath = path.join(
  workspaceDir,
  "output/presentation/Board-11_Group-2_CAABC-FL_Final_Defense_Limitations_v5.pptx",
);
const finalPath = path.join(
  workspaceDir,
  "output/presentation/Board-11_Group-2_CAABC-FL_Final_Defense_Research_Design_v7.pptx",
);
const stagingDir = path.join(workspaceDir, ".codex-finalizer");
const previewDir = path.join(workspaceDir, "tmp/ppt_build/research_design_after");
const skillDir = "C:/Users/HP/.codex/plugins/cache/openai-primary-runtime/presentations/26.909.12148/skills/presentations";
const runtimePython = "C:/Users/HP/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe";

const { finalizePresentation } = await import(
  pathToFileURL(path.join(skillDir, "container_tools/artifact_tool_utils.mjs")).href,
);

await fs.mkdir(stagingDir, { recursive: true });
await fs.mkdir(previewDir, { recursive: true });
await fs.mkdir(path.dirname(finalPath), { recursive: true });

const presentation = await PresentationFile.importPptx(await FileBlob.load(sourcePath));
const slide = presentation.resolve("sl/5onypobq");
if (!slide) throw new Error("Research Design slide not found.");

const FONT = "Arial";
const NAVY = "#062B6F";
const GREEN = "#008A46";
const TEAL = "#00A6A6";
const TEXT = "#263244";
const MUTED = "#5D6878";
const RULE = "#D8E1EA";
const PALE = "#F2F8FB";

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
    alignment: "left",
    verticalAlignment: "middle",
    autoFit: "shrinkText",
    ...style,
  };
  return shape;
}

// Preserve the title, logos, date, slide number and deck footer.
slide.shapes.add({
  geometry: "rect",
  name: "research-design-redesign-cover",
  position: { left: 31, top: 120, width: 1220, height: 520 },
  fill: "#FFFFFF",
  line: { fill: "none", width: 0 },
});

addText(
  "research-design-subtitle",
  "Controlled cross-silo comparison under one frozen protocol",
  { left: 135, top: 132, width: 1010, height: 32 },
  { fontSize: 18, color: MUTED, alignment: "center" },
);

// A single line connects the four stages without adding visual clutter.
slide.shapes.add({
  geometry: "rect",
  name: "research-design-process-line",
  position: { left: 177, top: 214, width: 906, height: 4 },
  fill: RULE,
  line: { fill: "none", width: 0 },
});

const stages = [
  {
    number: "1",
    title: "Cohort and partition",
    body: "PhysioNet 2019\n40,336 patients\nNatural Hospital A/B split",
    center: 180,
    accent: GREEN,
  },
  {
    number: "2",
    title: "Frozen protocol",
    body: "Five paired seeds\nSame MLP and evaluation split\nFixed privacy, CKKS and round budgets",
    center: 480,
    accent: NAVY,
  },
  {
    number: "3",
    title: "Comparative evaluation",
    body: "CAABC-FL and four baselines\nBenign and registered attacks\nUtility, privacy, robustness and system cost",
    center: 780,
    accent: TEAL,
  },
  {
    number: "4",
    title: "Statistical inference",
    body: "Paired confidence intervals and tests\nMultiplicity-aware interpretation\nClaims bounded to the evaluated protocol",
    center: 1080,
    accent: NAVY,
  },
];

for (const stage of stages) {
  slide.shapes.add({
    geometry: "ellipse",
    name: `research-design-stage-${stage.number}-node`,
    position: { left: stage.center - 29, top: 188, width: 58, height: 58 },
    fill: stage.accent,
    line: { fill: "#FFFFFF", width: 2 },
  });
  addText(
    `research-design-stage-${stage.number}-number`,
    stage.number,
    { left: stage.center - 29, top: 188, width: 58, height: 58 },
    { fontSize: 22, bold: true, color: "#FFFFFF", alignment: "center" },
  );
  addText(
    `research-design-stage-${stage.number}-title`,
    stage.title,
    { left: stage.center - 125, top: 262, width: 250, height: 35 },
    { fontSize: 20, bold: true, color: stage.accent, alignment: "center" },
  );
  slide.shapes.add({
    geometry: "rect",
    name: `research-design-stage-${stage.number}-rule`,
    position: { left: stage.center - 96, top: 304, width: 192, height: 2.3 },
    fill: stage.accent,
    line: { fill: "none", width: 0 },
  });
  addText(
    `research-design-stage-${stage.number}-body`,
    stage.body,
    { left: stage.center - 126, top: 316, width: 252, height: 106 },
    { fontSize: 16.5, color: TEXT, alignment: "center", verticalAlignment: "top" },
  );
}

slide.shapes.add({
  geometry: "roundRect",
  name: "research-design-control-band",
  position: { left: 115, top: 470, width: 1050, height: 105 },
  fill: PALE,
  line: { fill: "#A8C8D8", width: 1.2 },
});
addText(
  "research-design-control-label",
  "CONTROL PRINCIPLE",
  { left: 145, top: 480, width: 220, height: 28 },
  { fontSize: 14.5, bold: true, color: GREEN, alignment: "left" },
);
addText(
  "research-design-control-text",
  "Only the learning and aggregation method changes. The dataset, hospital split, MLP, privacy budget, CKKS parameters and round budget remain fixed.",
  { left: 145, top: 512, width: 990, height: 46 },
  { fontSize: 18, color: NAVY, alignment: "left", verticalAlignment: "top" },
);

slide.speakerNotes.textFrame.setText(
  "We used a controlled cross-silo research design. First, we retained the natural Hospital A and Hospital B partition of the 40,336-patient PhysioNet cohort. Second, every method used the same MLP, evaluation split, privacy budget, CKKS parameters, round budget, and five paired seeds. Third, we compared CAABC-FL with four baselines under benign and registered attack conditions, measuring utility, privacy, poisoning resilience, encrypted wire cost, and system timing. Finally, paired confidence intervals and statistical tests support direct method-level comparisons. This design isolates the learning and aggregation method while keeping every claim within the evaluated protocol.",
);

const after = await slide.export({ format: "png", scale: 2 });
await fs.writeFile(
  path.join(previewDir, "slide-22-after.png"),
  new Uint8Array(await after.arrayBuffer()),
);
const layout = await slide.export({ format: "layout" });
await fs.writeFile(path.join(previewDir, "slide-22-after.layout.json"), await layout.text());

const candidatePath = path.join(
  stagingDir,
  "Board-11_Group-2_CAABC-FL_Final_Defense_Research_Design_v7_candidate.pptx",
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
    referenceSha256: "ff1e7fbd819608ad1b0207b95ca697894c27a087444336c19da26b4454c7ccd2",
  },
  verifyArtifactToolImport: true,
  receiptPath: path.join(
    stagingDir,
    "Board-11_Group-2_CAABC-FL_Final_Defense_Research_Design_v7.validation.json",
  ),
});

console.log(JSON.stringify({ finalPath, slideCount: presentation.slides.items.length, result }, null, 2));
