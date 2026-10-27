import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = "E:/PrivacyPreserving-Healthcare-FL";
const sourcePath = path.join(
  workspaceDir,
  "output/presentation/Board-11_Group-2_CAABC-FL_Final_Defense_With_Conceptual_Framework_v2.pptx",
);
const finalPath = path.join(
  workspaceDir,
  "output/presentation/Board-11_Group-2_CAABC-FL_Final_Defense_With_Conceptual_Framework_and_Conclusion.pptx",
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
const futureWorkSlide = presentation.slides.getItem(32);
const slide = futureWorkSlide.duplicate();
slide.moveTo(33);

const titleShape = slide.shapes.items.find((shape) => shape.name === "Google Shape;211;p28");
if (!titleShape) throw new Error("Duplicated slide title was not found.");
titleShape.text.replace("Future Work", "Conclusion");

slide.shapes.add({
  geometry: "rect",
  name: "final-conclusion-content-cover",
  position: { left: 65, top: 125, width: 1150, height: 515 },
  fill: "#FFFFFF",
  line: { fill: "none", width: 0 },
});

const FONT = "Arial";
const NAVY = "#17365D";
const GREEN = "#008A46";
const TEXT = "#263244";
const MUTED = "#5B677A";
const RULE = "#C8D3DF";

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
  "final-conclusion-subtitle",
  "The study demonstrates an integrated and empirically evaluated approach to secure multi-institutional federated learning.",
  { left: 150, top: 128, width: 980, height: 40 },
  { fontSize: 17, color: MUTED, alignment: "center", italic: true },
);

const rows = [
  {
    label: "Integrated framework",
    color: GREEN,
    text: "CAABC-FL combines record-level privacy, ciphertext-aligned compression, CKKS-protected aggregation, controlled model release and auditable governance in one workflow.",
  },
  {
    label: "Experimental evidence",
    color: NAVY,
    text: "The registered experiments retained comparable predictive utility, reduced serialized encrypted upload, and limited membership and reconstruction exposure under the tested settings.",
  },
  {
    label: "Robust collaboration",
    color: GREEN,
    text: "Validation, reputation, rollback and audit controls improved resilience under the evaluated poisoning scenarios while preserving the protected aggregation path.",
  },
  {
    label: "Claim boundary",
    color: NAVY,
    text: "The results support a defensible research system rather than universal security or production readiness; broader clinical, threshold-custody and multi-host validation remains necessary.",
  },
];

rows.forEach((row, index) => {
  const y = 185 + index * 95;
  addText(`conclusion-label-${index + 1}`, row.label, { left: 105, top: y, width: 275, height: 62 }, {
    fontSize: 22,
    bold: true,
    color: row.color,
  });
  addText(`conclusion-text-${index + 1}`, row.text, { left: 400, top: y, width: 785, height: 62 }, {
    fontSize: 18,
    color: TEXT,
    verticalAlignment: "middle",
  });
  if (index < rows.length - 1) {
    slide.shapes.add({
      geometry: "rect",
      name: `conclusion-rule-${index + 1}`,
      position: { left: 95, top: y + 76, width: 1090, height: 1.2 },
      fill: RULE,
      line: { fill: "none", width: 0 },
    });
  }
});

slide.shapes.add({
  geometry: "roundRect",
  name: "final-conclusion-takeaway-box",
  position: { left: 155, top: 566, width: 970, height: 65 },
  fill: "#E8F4EE",
  line: { fill: GREEN, width: 1.6 },
});
addText(
  "final-conclusion-takeaway",
  "CAABC-FL shows that privacy, encrypted communication efficiency, poisoning resilience and accountability can be evaluated together within one multi-institutional learning protocol.",
  { left: 185, top: 574, width: 910, height: 48 },
  { fontSize: 18, bold: true, color: NAVY, alignment: "center" },
);

slide.speakerNotes.textFrame.setText(
  "The final conclusion is that CAABC-FL provides an integrated research framework rather than an isolated privacy or compression mechanism. It connects record-level differential privacy, ciphertext-aligned communication reduction, CKKS aggregation, model validation, controlled release, and auditable governance. The experiments provide evidence of comparable predictive utility, lower serialized encrypted upload, limited exposure under the registered privacy attacks, and improved resilience under evaluated poisoning conditions. These findings remain bounded to the tested data, attacks, seeds, and deployment environment. Production claims require broader clinical validation, dropout-tolerant threshold custody, and real multi-host confidential-computing experiments.",
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
  const previousNumber = index + 1 < 34 ? actualNumber : String(index + 1 === 34 ? 33 : index);
  pageShape.text.replace(previousNumber, actualNumber);
}

const candidatePath = path.join(
  stagingDir,
  "Board-11_Group-2_CAABC-FL_Final_Defense_With_Conceptual_Framework_and_Conclusion_candidate.pptx",
);
await (await PresentationFile.exportPptx(presentation)).save(candidatePath);

const tableOwners = [11, 12, 13, 14, 24, 27, 37];
const result = await finalizePresentation({
  explicitTotalSlideCount: 40,
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
    referenceSha256: "8c5c5b38fe52d03f6bfa17024039d211ff31914e51925fe080210425b76b6f19",
  },
  verifyArtifactToolImport: true,
  receiptPath: path.join(
    stagingDir,
    "Board-11_Group-2_CAABC-FL_Final_Defense_With_Conceptual_Framework_and_Conclusion.validation.json",
  ),
});

console.log(JSON.stringify({ finalPath, slideCount: presentation.slides.items.length, result }, null, 2));
