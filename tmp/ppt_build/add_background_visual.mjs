import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = "E:/PrivacyPreserving-Healthcare-FL";
const sourcePath = path.join(
  workspaceDir,
  "output/presentation/CAABC-FL_Final_Defense_25_September_2026_Complete_Reviewed.pptx",
);
const finalPath = path.join(
  workspaceDir,
  "output/presentation/CAABC-FL_Final_Defense_25_September_2026_Background_Visual_Reviewed.pptx",
);
const imagePath = path.join(
  workspaceDir,
  "output/presentation/assets/privacy_preserving_hospital_fl_background_v1.png",
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
const slide = presentation.slides.getItem(3);
const bullets = slide.shapes.getItem("background-bullets");
const takeaway = slide.shapes.getItem("background-takeaway");
if (!bullets || !takeaway) throw new Error("Background slide anchors were not found.");

bullets.text =
  "Hospitals hold complementary clinical data, but direct pooling raises privacy, ownership, and breach risks.\n" +
  "Federated learning keeps patient records local, yet model updates may still expose membership or training features [1]–[6].\n" +
  "Encryption protects update values, but it increases communication cost and limits plaintext poisoning defenses.";
bullets.position.set({ left: 92, top: 162, width: 500, height: 345 });
bullets.text.style = {
  typeface: "Arial",
  fontSize: 22,
  color: "#1F2937",
  verticalAlignment: "top",
  autoFit: "shrinkText",
};

takeaway.text =
  "Research gap: Existing work usually evaluates privacy, communication efficiency, robustness, and governance as separate problems.";
takeaway.position.set({ left: 100, top: 525, width: 495, height: 82 });
takeaway.text.style = {
  typeface: "Arial",
  fontSize: 20,
  bold: true,
  color: "#008A46",
  alignment: "left",
  verticalAlignment: "middle",
  autoFit: "shrinkText",
};

const imageBytes = await fs.readFile(imagePath);
slide.images.add({
  blob: imageBytes,
  contentType: "image/png",
  alt: "Three hospitals contribute protected model updates to a shielded federated learning process and a shared model.",
  fit: "contain",
  position: { left: 620, top: 158, width: 595, height: 410 },
  prompt:
    "Academic illustration of privacy-preserving federated learning across three hospitals, with encrypted data streams, a central shielded model, and a shared output model; navy, cyan, and green on white; no text.",
});

slide.speakerNotes.textFrame.setText(
  "Federated learning reduces the need to exchange raw patient records, but it does not solve every privacy and integrity problem. The illustration summarizes the setting: hospitals retain their data, protected model updates support collaborative learning, and the system produces a shared model. This thesis studies update protection, encrypted transport, poisoning response, and release governance. Sources: McMahan et al. [1], Sheller et al. [2], Dayan et al. [3], Shokri et al. [4], Zhu et al. [5], and Geiping et al. [6]. The illustration is conceptual and does not represent an experimental result.",
);

const candidatePath = path.join(
  stagingDir,
  "CAABC-FL_Final_Defense_25_September_2026_Background_Visual_Reviewed_candidate.pptx",
);
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
    referenceSha256: "2d16438a6bd9bbed918e4ccb57d1edd14e93e1e729ac9181cb68c21f916aac85",
  },
  verifyArtifactToolImport: true,
  receiptPath: path.join(
    stagingDir,
    "CAABC-FL_Final_Defense_25_September_2026_Background_Visual_Reviewed.validation.json",
  ),
});

console.log(JSON.stringify({ finalPath, result }, null, 2));
