import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = "E:/PrivacyPreserving-Healthcare-FL";
const sourcePath = path.join(workspaceDir, "output/presentation/CAABC-FL_Final_Defense_25_September_2026_Title_Background.pptx");
const finalPath = path.join(workspaceDir, "output/presentation/CAABC-FL_Final_Defense_25_September_2026_Complete_Reviewed.pptx");
const stagingDir = path.join(workspaceDir, ".codex-finalizer");
const skillDir = "C:/Users/HP/.codex/plugins/cache/openai-primary-runtime/presentations/26.909.12148/skills/presentations";
const runtimePython = "C:/Users/HP/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe";

const { finalizePresentation } = await import(
  pathToFileURL(path.join(skillDir, "container_tools/artifact_tool_utils.mjs")).href,
);

await fs.mkdir(stagingDir, { recursive: true });
await fs.mkdir(path.dirname(finalPath), { recursive: true });

const presentation = await PresentationFile.importPptx(await FileBlob.load(sourcePath));

// Store source-slide references before inserting any duplicates.
const objectivesSource = presentation.slides.getItem(6);
const analysisSource = presentation.slides.getItem(16);
const budgetSource = presentation.slides.getItem(17);
const systemApproachSource = presentation.slides.getItem(13);
const secondReferencesSource = presentation.slides.getItem(28);

const shape = (slide, name) => {
  const item = slide.shapes.getItem(name);
  if (!item) throw new Error(`Missing shape '${name}' on slide ${slide.index + 1}`);
  return item;
};

// Keep the existing compact contents slide and acknowledge the backup section.
presentation.resolve("sh/ove9o7yd").text.replace(
  "6  References and Q&A",
  "6  References, Backup and Q&A",
);

// Research Questions: reuse the three-objective visual rhythm.
const questionsSlide = objectivesSource.duplicate();
questionsSlide.moveTo(objectivesSource.index + 1);
questionsSlide.placeholders.getItem("title").text = "Research Questions";
shape(questionsSlide, "objective-text-1").text =
  "How can multi-institutional learning protect patient records, model updates, and release decisions without centralizing raw data?";
shape(questionsSlide, "objective-text-2").text =
  "Can CAABC-FL reduce serialized encrypted communication while maintaining predictive utility?";
shape(questionsSlide, "objective-text-3").text =
  "How does the framework compare with relevant baselines under benign and adversarial conditions?";
for (const name of ["objective-text-1", "objective-text-2", "objective-text-3"]) {
  shape(questionsSlide, name).text.style = {
    typeface: "Arial",
    fontSize: 25,
    color: "#1F2937",
    verticalAlignment: "middle",
    autoFit: "shrinkText",
  };
}
// The questions are longer than the source objectives, so give every item a
// separate reading band instead of relying on shrink-to-fit alone.
const questionBands = [
  { circle: "objective-1", text: "objective-text-1", top: 145 },
  { circle: "objective-2", text: "objective-text-2", top: 305 },
  { circle: "objective-3", text: "objective-text-3", top: 465 },
];
for (const band of questionBands) {
  shape(questionsSlide, band.circle).position.set({
    left: 125,
    top: band.top,
    width: 82,
    height: 82,
  });
  shape(questionsSlide, band.text).position.set({
    left: 245,
    top: band.top - 15,
    width: 920,
    height: 120,
  });
}
questionsSlide.speakerNotes.textFrame.setText(
  "RQ1 addresses the integrated privacy and trust architecture. RQ2 tests whether ciphertext-aligned compression produces real serialized communication savings without material utility loss. RQ3 evaluates the resulting system under benign and adversarial conditions using the registered protocol.",
);

// Problem formulation: reuse the four-quadrant analytical layout.
const formulationSlide = analysisSource.duplicate();
formulationSlide.moveTo(systemApproachSource.index + 1);
formulationSlide.placeholders.getItem("title").text = "Problem Formulation";
const formulation = [
  [
    "analysis-heading-0",
    "Learning objective",
    "analysis-body-0",
    "F(w) = Σₖ (nₖ/N)Fₖ(w)\nFₖ(w) = (1/nₖ)Σᵢ ℓ(w; xᵢ, yᵢ)",
  ],
  [
    "analysis-heading-1",
    "Protected local update",
    "analysis-body-1",
    "ḡₖᵗ = gₖᵗ / max(1, ||gₖᵗ||₂/C)\nuₖᵗ = Qₛₜ(ḡₖᵗ + zₖᵗ + eₖᵗ)",
  ],
  [
    "analysis-heading-2",
    "Encrypted aggregation",
    "analysis-body-2",
    "cₜ = ⊕ₖ∈Aₜ Encₚₖ(uₖᵗ)\nwₜ₊₁ = wₜ − ηₜ Decₜ(cₜ)/|Aₜ|",
  ],
  [
    "analysis-heading-3",
    "Design constraints",
    "analysis-body-3",
    "Minimize final loss and serialized bytes subject to record-level DP, verified aggregation, threshold-authorized release, and auditable execution.",
  ],
];
for (const [headingName, headingText, bodyName, bodyText] of formulation) {
  shape(formulationSlide, headingName).text = headingText;
  shape(formulationSlide, bodyName).text = bodyText;
  shape(formulationSlide, bodyName).text.style = {
    typeface: "Arial",
    fontSize: 23,
    color: "#1F2937",
    verticalAlignment: "middle",
    autoFit: "shrinkText",
  };
}
formulationSlide.speakerNotes.textFrame.setText(
  "Notation: K is the number of institutions, D_k is the local dataset, C is the clipping norm, z_k is Gaussian noise, e_k is the error-feedback residual, Q selects the common ciphertext-aligned blocks, A_t is the accepted client set, and Dec_t denotes policy-governed decryption after verification and quorum checks.",
);

// Project timeline: retain the native three-column table as an editable Gantt summary.
const timelineSlide = budgetSource.duplicate();
timelineSlide.moveTo(secondReferencesSource.index + 1);
timelineSlide.placeholders.getItem("title").text = "Project Timeline";
shape(timelineSlide, "budget-summary").text = "Research phases from proposal to final defense";
shape(timelineSlide, "table-caption-budget").text = "GANTT SUMMARY. Completed project milestones";
shape(timelineSlide, "budget-note").text = "Final defense: 25 September 2026";
const timelineTable = timelineSlide.tables.items[0];
if (!timelineTable) throw new Error("Timeline source table was not preserved during duplication.");
const timelineValues = [
  ["Phase", "Period", "Status"],
  ["Proposal, literature review, and research design", "Jun–Nov 2025", "Completed"],
  ["Framework implementation", "Dec 2025–Mar 2026", "Completed"],
  ["Security, privacy, poisoning, and statistical evaluation", "Apr–Jul 2026", "Completed"],
  ["Report writing, revision, and defense preparation", "Jul–Sep 2026", "Completed"],
];
for (let r = 0; r < timelineValues.length; r += 1) {
  for (let c = 0; c < timelineValues[r].length; c += 1) {
    timelineTable.cells.set(r, c, timelineValues[r][c]);
  }
}
for (let r = 1; r < 5; r += 1) {
  const status = timelineTable.getCell(r, 2);
  status.fill = "#E7F4EC";
  status.text.style = {
    typeface: "Arial",
    fontSize: 18,
    bold: true,
    color: "#008A46",
  };
}
timelineSlide.speakerNotes.textFrame.setText(
  "This backup slide summarizes the principal project phases. The periods consolidate the detailed working timeline used during the proposal, implementation, evaluation, writing, and defense stages.",
);

// Abbreviations: reuse the four-quadrant layout as a compact backup glossary.
const abbreviationsSlide = analysisSource.duplicate();
abbreviationsSlide.moveTo(timelineSlide.index + 1);
abbreviationsSlide.placeholders.getItem("title").text = "Abbreviations";
const abbreviationGroups = [
  [
    "analysis-heading-0",
    "Framework and privacy",
    "analysis-body-0",
    "CAABC-FL: Ciphertext-Aligned Adaptive Block Compression for Federated Learning\nFL: Federated Learning\nDP: Differential Privacy",
  ],
  [
    "analysis-heading-1",
    "Cryptography and systems",
    "analysis-body-1",
    "CKKS: Approximate homomorphic encryption\nHE: Homomorphic Encryption\nTEE: Trusted Execution Environment",
  ],
  [
    "analysis-heading-2",
    "Evaluation",
    "analysis-body-2",
    "AUROC: Area Under the ROC Curve\nAUPRC: Area Under the Precision-Recall Curve\nMCC: Matthews Correlation Coefficient",
  ],
  [
    "analysis-heading-3",
    "Attacks and deployment",
    "analysis-body-3",
    "MIA: Membership Inference Attack\nLiRA/RMIA: Membership inference tests\nASR: Attack Success Rate\nTPR/FPR: True-/False-Positive Rate\nWAN: Wide-Area Network",
  ],
];
for (const [headingName, headingText, bodyName, bodyText] of abbreviationGroups) {
  shape(abbreviationsSlide, headingName).text = headingText;
  shape(abbreviationsSlide, bodyName).text = bodyText;
  shape(abbreviationsSlide, bodyName).text.style = {
    typeface: "Arial",
    fontSize: bodyName === "analysis-body-3" ? 18 : 19,
    color: "#1F2937",
    verticalAlignment: "middle",
    autoFit: "shrinkText",
  };
}
abbreviationsSlide.speakerNotes.textFrame.setText(
  "Backup glossary for acronyms used throughout the defense presentation.",
);

// Keep both backup slides together after the references and before Q&A.
timelineSlide.moveTo(31);
abbreviationsSlide.moveTo(32);

// Inserted slides inherit the source slide's hard-coded page number. Refresh
// every footer number after the final slide order has been established.
const finalSnapshot = await presentation.inspect({
  kind: "textbox",
  include: "id,slide,text,bbox",
  maxChars: 120000,
});
for (const line of finalSnapshot.ndjson.split("\n").filter(Boolean)) {
  const record = JSON.parse(line);
  const [left, top] = record.bbox ?? [0, 0, 0, 0];
  if (record.slide > 1 && top > 620 && left > 1100) {
    presentation.resolve(record.id).text = String(record.slide);
  }
}

const candidatePath = path.join(stagingDir, "CAABC-FL_Final_Defense_25_September_2026_Complete_Reviewed_candidate.pptx");
await (await PresentationFile.exportPptx(presentation)).save(candidatePath);

const tableOwners = [10, 11, 12, 20, 23, 32];
const result = await finalizePresentation({
  explicitTotalSlideCount: 35,
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
  requiredNativeChartOwnerSlides: [23],
  nativeChartTargetApplication: "powerpoint",
  fontPolicy: {
    basis: "reference",
    families: ["Arial", "Corbel"],
    referencePath: sourcePath,
    referenceSha256: "6fddfbc71501ca3bdf0ce11ecfc129df2b6c1b15dcd3bb452331381b423a96bc",
  },
  verifyArtifactToolImport: true,
  receiptPath: path.join(stagingDir, "CAABC-FL_Final_Defense_25_September_2026_Complete_Reviewed.validation.json"),
});

console.log(JSON.stringify({
  finalPath,
  addedSlides: [
    { title: "Research Questions", slide: questionsSlide.index + 1 },
    { title: "Problem Formulation", slide: formulationSlide.index + 1 },
    { title: "Project Timeline", slide: timelineSlide.index + 1 },
    { title: "Abbreviations", slide: abbreviationsSlide.index + 1 },
  ],
  result,
}, null, 2));
