import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = "E:/PrivacyPreserving-Healthcare-FL";
const sourcePath = path.join(
  workspaceDir,
  "output/presentation/CAABC-FL_Final_Defense_25_September_2026_Motivation_Evidence_Reviewed.pptx",
);
const finalPath = path.join(
  workspaceDir,
  "output/presentation/CAABC-FL_Final_Defense_25_September_2026_Problem_Paragraph_Reviewed.pptx",
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
const slide = presentation.slides.getItem(4);
const bullets = slide.shapes.getItem("problem-bullets");
const question = slide.shapes.getItem("research-question");
if (!bullets || !question) throw new Error("Problem Statement slide anchors were not found.");

bullets.delete();
const paragraph = slide.shapes.add({
  geometry: "textbox",
  name: "problem-paragraph",
  position: { left: 105, top: 155, width: 1070, height: 310 },
  fill: "none",
  line: { fill: "none", width: 0 },
});
paragraph.text =
  "Although federated learning keeps patient records within each institution, the gradients and model updates exchanged during training may still expose sensitive information through membership inference or reconstruction attacks. Applying CKKS encryption protects update values, but it increases the serialized communication payload and prevents many poisoning defenses from examining individual plaintext updates. Existing systems may also depend on centralized decryption, unverifiable aggregation, or limited audit evidence, which concentrates trust and reduces accountability. Current approaches therefore seldom provide record-level privacy, practical encrypted communication, poisoning resilience, and independently verifiable governance within one evaluated multi-institutional healthcare framework.";
paragraph.text.style = {
  typeface: "Arial",
  fontSize: 24,
  color: "#1F2937",
  alignment: "left",
  verticalAlignment: "middle",
  autoFit: "shrinkText",
};

question.position.set({ left: 120, top: 495, width: 1040, height: 115 });
question.text =
  "Research question\nHow can multiple institutions train a useful shared model while limiting privacy exposure, encrypted communication cost, poisoning damage, and unilateral control?";
question.text.style = {
  typeface: "Arial",
  fontSize: 23,
  bold: true,
  color: "#1E3A5F",
  alignment: "center",
  verticalAlignment: "middle",
  autoFit: "shrinkText",
};

slide.speakerNotes.textFrame.setText(
  "Federated learning keeps source records local, but exchanged updates can still leak information. CKKS improves confidentiality while increasing communication cost and hiding the update geometry used by many poisoning defenses. Centralized decryption, unverified aggregation, and limited audit evidence create additional trust concerns. The thesis therefore treats privacy, efficiency, adversarial resilience, and release governance as one engineering problem.",
);

const candidatePath = path.join(
  stagingDir,
  "CAABC-FL_Final_Defense_25_September_2026_Problem_Paragraph_Reviewed_candidate.pptx",
);
await (await PresentationFile.exportPptx(presentation)).save(candidatePath);

const tableOwners = [11, 12, 13, 21, 24, 33];
const result = await finalizePresentation({
  explicitTotalSlideCount: 36,
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
  requiredNativeChartOwnerSlides: [7, 24],
  nativeChartTargetApplication: "powerpoint",
  fontPolicy: {
    basis: "reference",
    families: ["Arial", "Corbel"],
    referencePath: sourcePath,
    referenceSha256: "63762eba49e2e6734c69397de4ddf6659ed6f4dfc21c5b8da9eb534fc7cd2cf1",
  },
  verifyArtifactToolImport: true,
  receiptPath: path.join(
    stagingDir,
    "CAABC-FL_Final_Defense_25_September_2026_Problem_Paragraph_Reviewed.validation.json",
  ),
});

console.log(JSON.stringify({ finalPath, result }, null, 2));
