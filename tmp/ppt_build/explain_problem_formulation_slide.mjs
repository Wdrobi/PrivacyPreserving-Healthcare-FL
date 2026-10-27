import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = "E:/PrivacyPreserving-Healthcare-FL";
const sourcePath = path.join(
  workspaceDir,
  "output/presentation/CAABC-FL_Final_Defense_25_September_2026_System_Approach_Professional_v2.pptx",
);
const finalPath = path.join(
  workspaceDir,
  "output/presentation/CAABC-FL_Final_Defense_25_September_2026_Problem_Formulation_Explained.pptx",
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
const slide = presentation.slides.getItem(18);

const FONT = "Arial";
const NAVY = "#1E3A5F";
const GREEN = "#008A46";
const CYAN = "#00A9D6";
const TEXT = "#1F2937";
const MUTED = "#52606D";

slide.shapes.add({
  geometry: "rect",
  name: "problem-formulation-explanation-cover",
  position: { left: 42, top: 126, width: 1196, height: 520 },
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
    verticalAlignment: "middle",
    autoFit: "shrinkText",
    ...style,
  };
  return shape;
}

function addRule(name, x, y, w, color) {
  slide.shapes.add({
    geometry: "rect",
    name,
    position: { left: x, top: y, width: w, height: 3 },
    fill: color,
    line: { fill: "none", width: 0 },
  });
}

function addSection({ prefix, title, accent, x, y, equation, explanation, takeaway }) {
  addText(`${prefix}-title`, title, { left: x, top: y, width: 505, height: 36 }, {
    fontSize: 27,
    bold: true,
    color: accent,
  });
  addRule(`${prefix}-rule`, x, y + 42, 505, accent);
  addText(`${prefix}-equation`, equation, { left: x + 8, top: y + 55, width: 485, height: 66 }, {
    fontSize: 23,
    color: TEXT,
    verticalAlignment: "middle",
  });
  addText(`${prefix}-explanation`, explanation, { left: x + 8, top: y + 122, width: 485, height: 57 }, {
    fontSize: 15,
    color: MUTED,
    verticalAlignment: "top",
  });
  addText(`${prefix}-takeaway`, takeaway, { left: x + 8, top: y + 179, width: 485, height: 30 }, {
    fontSize: 15,
    bold: true,
    color: accent,
    verticalAlignment: "top",
  });
}

addSection({
  prefix: "learning-objective",
  title: "Learning objective",
  accent: GREEN,
  x: 95,
  y: 143,
  equation: "F(w) = Σₖ (nₖ/N)Fₖ(w)\nFₖ(w) = (1/nₖ)Σᵢ ℓ(w; xᵢ, yᵢ)",
  explanation: "Fₖ(w) is the empirical loss at hospital k. The ratio nₖ/N weights each hospital by its share of the combined training records.",
  takeaway: "Goal: minimize weighted global loss while records remain local.",
});

addSection({
  prefix: "protected-update",
  title: "Protected local update",
  accent: CYAN,
  x: 680,
  y: 143,
  equation: "ḡₖᵗ = gₖᵗ / max(1, ‖gₖᵗ‖₂/C)\nuₖᵗ = Qₛₜ(ḡₖᵗ + zₖᵗ + eₖᵗ)",
  explanation: "C bounds each gradient. zₖᵗ adds Gaussian DP noise, eₖᵗ carries the compression residual, and Qₛₜ applies the CAABC-FL block compressor.",
  takeaway: "Result: a bounded, private and compression-aware client update.",
});

addSection({
  prefix: "encrypted-aggregation",
  title: "Encrypted aggregation",
  accent: GREEN,
  x: 95,
  y: 370,
  equation: "cₜ = ⊕ₖ∈Aₜ Encₚₖ(uₖᵗ)\nwₜ₊₁ = wₜ − ηₜ Dec(cₜ)/|Aₜ|",
  explanation: "Aₜ contains admitted clients. CKKS sums encrypted uₖᵗ values without exposing them. Custodians decrypt cₜ, the aggregate, rather than individual updates.",
  takeaway: "ηₜ controls the update step and |Aₜ| produces the mean aggregate.",
});

addText("constraints-title", "Design constraints", { left: 680, top: 370, width: 505, height: 36 }, {
  fontSize: 27,
  bold: true,
  color: NAVY,
});
addRule("constraints-rule", 680, 412, 505, CYAN);
addText(
  "constraints-objective",
  "Minimize prediction loss and serialized upload subject to:",
  { left: 688, top: 427, width: 485, height: 34 },
  { fontSize: 18, bold: true, color: TEXT },
);
addText(
  "constraints-list-left",
  "Privacy\nIntegrity",
  { left: 688, top: 466, width: 115, height: 62 },
  { fontSize: 16, bold: true, color: NAVY, verticalAlignment: "top" },
);
addText(
  "constraints-values-left",
  "Record-level differential privacy\nIndependently checked aggregate",
  { left: 800, top: 466, width: 365, height: 62 },
  { fontSize: 16, color: MUTED, verticalAlignment: "top" },
);
addText(
  "constraints-list-right",
  "Release\nAudit",
  { left: 688, top: 526, width: 115, height: 62 },
  { fontSize: 16, bold: true, color: NAVY, verticalAlignment: "top" },
);
addText(
  "constraints-values-right",
  "Threshold authorization\nPermissioned execution evidence",
  { left: 800, top: 526, width: 365, height: 62 },
  { fontSize: 16, color: MUTED, verticalAlignment: "top" },
);

slide.shapes.add({
  geometry: "rect",
  name: "problem-formulation-column-divider",
  position: { left: 638, top: 148, width: 1.5, height: 438 },
  fill: "#D7DEE7",
  line: { fill: "none", width: 0 },
});

addText(
  "problem-formulation-round-summary",
  "One training round constructs protected local updates, aggregates ciphertexts, and releases only a validated global model.",
  { left: 225, top: 600, width: 830, height: 34 },
  { fontSize: 16, italic: true, color: NAVY, alignment: "center" },
);

slide.speakerNotes.textFrame.setText(
  "The formulation has four parts. First, the global objective is the sample-weighted average of hospital losses, where n_k is the number of records at hospital k and N is the total across participating hospitals. Second, each gradient is clipped to norm C, Gaussian noise z_k^t provides record-level differential privacy, and the residual e_k^t preserves information lost by CAABC-FL compression Q_s_t. Third, the accepted client set A_t contributes encrypted updates to the CKKS sum c_t. Threshold custodians decrypt only this aggregate, and eta_t is the global learning rate. Finally, the design must reduce predictive loss and serialized communication while satisfying privacy, integrity, threshold-release, and audit requirements.",
);

const candidatePath = path.join(
  stagingDir,
  "CAABC-FL_Final_Defense_25_September_2026_Problem_Formulation_Explained_candidate.pptx",
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
    referenceSha256: "9b0c215955b03275a5ddf8c2e4868f1cd18a430a4a3f57c0a3faef3559ec9084",
  },
  verifyArtifactToolImport: true,
  receiptPath: path.join(
    stagingDir,
    "CAABC-FL_Final_Defense_25_September_2026_Problem_Formulation_Explained.validation.json",
  ),
});

console.log(JSON.stringify({ finalPath, slideCount: presentation.slides.items.length, result }, null, 2));
