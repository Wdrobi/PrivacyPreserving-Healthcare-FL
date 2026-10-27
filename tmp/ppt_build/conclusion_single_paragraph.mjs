import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = "E:/PrivacyPreserving-Healthcare-FL";
const sourcePath = path.join(
  workspaceDir,
  "output/presentation/Board-11_Group-2_CAABC-FL_Final_Defense_With_Conceptual_Framework_and_Conclusion.pptx",
);
const finalPath = path.join(
  workspaceDir,
  "output/presentation/Board-11_Group-2_CAABC-FL_Final_Defense_Conclusion_Paragraph.pptx",
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
const slide = presentation.slides.getItem(33);

// Cover the previous multi-part conclusion while preserving the template title,
// logos, border, date, footer, and slide number.
slide.shapes.add({
  geometry: "rect",
  name: "single-paragraph-conclusion-cover",
  position: { left: 65, top: 125, width: 1150, height: 515 },
  fill: "#FFFFFF",
  line: { fill: "none", width: 0 },
});

const paragraph = slide.shapes.add({
  geometry: "textbox",
  name: "single-paragraph-conclusion",
  position: { left: 145, top: 205, width: 990, height: 300 },
  fill: "none",
  line: { fill: "none", width: 0 },
});
paragraph.text = "This thesis developed CAABC-FL as an integrated framework for secure multi-institutional federated learning. The system combines record-level differential privacy, ciphertext-aligned adaptive compression, CKKS-protected aggregation, controlled model release, poisoning-aware validation, and auditable governance within a single workflow. Across the registered experiments, CAABC-FL maintained comparable predictive utility, reduced serialized encrypted upload, limited membership-inference and gradient-reconstruction exposure, and improved resilience under the evaluated poisoning scenarios. These findings demonstrate that privacy, communication efficiency, robustness, and accountability can be addressed together, while broader clinical validation, real multi-host deployment, and dropout-tolerant threshold custody remain necessary before production use.";
paragraph.text.style = {
  typeface: "Arial",
  fontSize: 23,
  color: "#263244",
  alignment: "left",
  verticalAlignment: "middle",
  autoFit: "shrinkText",
};

slide.speakerNotes.textFrame.setText(
  "CAABC-FL brings privacy protection, encrypted aggregation, communication reduction, poisoning-aware controls, and accountable governance into one multi-institutional learning workflow. The experiments support comparable predictive utility, lower serialized encrypted upload, limited exposure under the evaluated privacy attacks, and stronger resilience under the tested poisoning scenarios. The conclusion remains bounded to the registered datasets, attacks, seeds, and deployment environment. Production use requires broader clinical validation, a real multi-host deployment, and dropout-tolerant threshold custody.",
);

const candidatePath = path.join(
  stagingDir,
  "Board-11_Group-2_CAABC-FL_Final_Defense_Conclusion_Paragraph_candidate.pptx",
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
    referenceSha256: "9b105c11284f1c1ab6775c666f6061193ff23e0493d107e050622ad172995d60",
  },
  verifyArtifactToolImport: true,
  receiptPath: path.join(
    stagingDir,
    "Board-11_Group-2_CAABC-FL_Final_Defense_Conclusion_Paragraph_v2.validation.json",
  ),
});

console.log(JSON.stringify({ finalPath, slideCount: presentation.slides.items.length, result }, null, 2));
