import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = "E:/PrivacyPreserving-Healthcare-FL";
const sourcePath = path.join(
  workspaceDir,
  "output/presentation/Board-11_Group-2_CAABC-FL_Final_Defense_With_CAABC_Algorithm_v3.pptx",
);
const finalPath = path.join(
  workspaceDir,
  "output/presentation/Board-11_Group-2_CAABC-FL_Final_Defense_With_Algorithm_Gradient_Reconstruction_v4.pptx",
);
const stagingDir = path.join(workspaceDir, ".codex-finalizer");
const previewDir = path.join(workspaceDir, "tmp/ppt_build/key_findings_after");
const skillDir = "C:/Users/HP/.codex/plugins/cache/openai-primary-runtime/presentations/26.909.12148/skills/presentations";
const runtimePython = "C:/Users/HP/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe";

const { finalizePresentation } = await import(
  pathToFileURL(path.join(skillDir, "container_tools/artifact_tool_utils.mjs")).href,
);

await fs.mkdir(stagingDir, { recursive: true });
await fs.mkdir(previewDir, { recursive: true });
await fs.mkdir(path.dirname(finalPath), { recursive: true });

const presentation = await PresentationFile.importPptx(await FileBlob.load(sourcePath));
const slide = presentation.resolve("sl/3mdove10");
if (!slide) throw new Error("Key Findings slide not found.");

const before = await slide.export({ format: "png", scale: 2 });
await fs.writeFile(
  path.join(previewDir, "slide-28-before.png"),
  new Uint8Array(await before.arrayBuffer()),
);

const membershipValue = presentation.resolve("sh/p0ripov6");
const membershipLabel = presentation.resolve("sh/zudkvix8");
if (!membershipValue || !membershipLabel) {
  throw new Error("Privacy metric shapes were not found on Key Findings slide.");
}

membershipValue.text = "0.5035";
membershipValue.position = { left: 975, top: 165, width: 250, height: 64 };
membershipValue.text.style = {
  typeface: "Arial",
  fontSize: 36,
  bold: true,
  color: "#123968",
  alignment: "center",
  verticalAlignment: "middle",
  autoFit: "shrinkText",
};

membershipLabel.text = "Membership attack AUC";
membershipLabel.position = { left: 975, top: 225, width: 250, height: 42 };
membershipLabel.text.style = {
  typeface: "Arial",
  fontSize: 17.5,
  bold: true,
  color: "#123968",
  alignment: "center",
  verticalAlignment: "middle",
  autoFit: "shrinkText",
};

slide.shapes.add({
  geometry: "rect",
  name: "privacy-metric-divider",
  position: { left: 1008, top: 272, width: 184, height: 1.4 },
  fill: "#B6C4D2",
  line: { fill: "none", width: 0 },
});

const reconstructionValue = slide.shapes.add({
  geometry: "textbox",
  name: "gradient-reconstruction-rmse-value",
  position: { left: 965, top: 279, width: 270, height: 47 },
  fill: "none",
  line: { fill: "none", width: 0 },
});
reconstructionValue.text = "0.684 to 2.763";
reconstructionValue.text.style = {
  typeface: "Arial",
  fontSize: 28,
  bold: true,
  color: "#008A46",
  alignment: "center",
  verticalAlignment: "middle",
  autoFit: "shrinkText",
};

const reconstructionLabel = slide.shapes.add({
  geometry: "textbox",
  name: "gradient-reconstruction-rmse-label",
  position: { left: 965, top: 324, width: 270, height: 48 },
  fill: "none",
  line: { fill: "none", width: 0 },
});
reconstructionLabel.text = "Reconstruction RMSE (300 steps)\nHigher means less accurate recovery";
reconstructionLabel.text.style = {
  typeface: "Arial",
  fontSize: 14.5,
  bold: true,
  color: "#123968",
  alignment: "center",
  verticalAlignment: "middle",
  autoFit: "shrinkText",
};

const existingNotes = slide.speakerNotes?.textFrame?.text?.trim?.() ?? "";
slide.speakerNotes.textFrame.setText([
  existingNotes,
  "Gradient-reconstruction evidence: under the registered 300-step attack, RMSE increased from 0.684 for plaintext-exact exposure to 2.763 for DP plus CAABC-FL. Higher RMSE means the attacker recovered the input features less accurately. This result is attack-specific empirical evidence; the differential privacy accountant provides the formal privacy guarantee.",
].filter(Boolean).join("\n\n"));

const after = await slide.export({ format: "png", scale: 2 });
await fs.writeFile(
  path.join(previewDir, "slide-28-after.png"),
  new Uint8Array(await after.arrayBuffer()),
);
const layout = await slide.export({ format: "layout" });
await fs.writeFile(path.join(previewDir, "slide-28-after.layout.json"), await layout.text());

const montage = await presentation.export({ format: "webp", montage: true, scale: 0.5 });
await fs.writeFile(
  path.join(previewDir, "deck-montage.webp"),
  new Uint8Array(await montage.arrayBuffer()),
);

const candidatePath = path.join(
  stagingDir,
  "Board-11_Group-2_CAABC-FL_Final_Defense_With_Algorithm_Gradient_Reconstruction_candidate.pptx",
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
    referenceSha256: "00def8cf4bb1bde315ba4fbd093c24543269e684db73d1fd06623acb2d8c67e7",
  },
  verifyArtifactToolImport: true,
  receiptPath: path.join(
    stagingDir,
    "Board-11_Group-2_CAABC-FL_Final_Defense_With_Algorithm_Gradient_Reconstruction_v4.validation.json",
  ),
});

console.log(JSON.stringify({ finalPath, slideCount: presentation.slides.items.length, result }, null, 2));
