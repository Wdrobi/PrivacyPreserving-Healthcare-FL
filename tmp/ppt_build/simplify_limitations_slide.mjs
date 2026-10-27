import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = "E:/PrivacyPreserving-Healthcare-FL";
const sourcePath = path.join(
  workspaceDir,
  "output/presentation/Board-11_Group-2_CAABC-FL_Final_Defense_Contributions_v3.pptx",
);
const finalPath = path.join(
  workspaceDir,
  "output/presentation/Board-11_Group-2_CAABC-FL_Final_Defense_Limitations_v5.pptx",
);
const stagingDir = path.join(workspaceDir, ".codex-finalizer");
const previewDir = path.join(workspaceDir, "tmp/ppt_build/limitations_after");
const skillDir = "C:/Users/HP/.codex/plugins/cache/openai-primary-runtime/presentations/26.909.12148/skills/presentations";
const runtimePython = "C:/Users/HP/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe";

const { finalizePresentation } = await import(
  pathToFileURL(path.join(skillDir, "container_tools/artifact_tool_utils.mjs")).href,
);

await fs.mkdir(stagingDir, { recursive: true });
await fs.mkdir(previewDir, { recursive: true });
await fs.mkdir(path.dirname(finalPath), { recursive: true });

const presentation = await PresentationFile.importPptx(await FileBlob.load(sourcePath));
const slide = presentation.resolve("sl/ofu103u5");
if (!slide) throw new Error("Limitations slide not found.");

const body = presentation.resolve("sh/7ux8jm1k");
const boundary = presentation.resolve("sh/mto7qh0f");
if (!body || !boundary) throw new Error("Limitations text shapes not found.");

body.text = [
  "External validity: One retrospective sepsis cohort, two source hospitals, and one MLP. No prospective or external clinical validation.",
  "Key governance: The main TenSEAL path retains central key custody. The OpenFHE threshold test remains an isolated 3-of-3 experiment.",
  "Deployment realism: Timing came from sequential single-host runs. No wide-area deployment or physical TDX/SEV-SNP cluster was tested.",
  "Evaluation scope: Privacy and poisoning conclusions cover only the registered attacks, five seeds, and evaluated trust assumptions.",
].join("\n");
body.text.style = {
  typeface: "Arial",
  fontSize: 20,
  color: "#263244",
  alignment: "left",
  verticalAlignment: "top",
  autoFit: "shrinkText",
};

boundary.text = "Evidence supports bounded protocol-level claims. Clinical and production-security validation remain future work.";
boundary.text.style = {
  typeface: "Arial",
  fontSize: 17.5,
  bold: true,
  color: "#C00000",
  alignment: "center",
  verticalAlignment: "middle",
  autoFit: "shrinkText",
};

slide.speakerNotes.textFrame.setText(
  "Our limitations define the boundary of the evidence. First, we used one retrospective sepsis cohort, two source hospitals, and one MLP, without prospective or external clinical validation. Second, the main TenSEAL path still uses central key custody, while threshold decryption was tested only as an isolated 3-of-3 experiment without dropout tolerance. Third, system timing came from sequential single-host runs rather than a real wide-area deployment or physical confidential-computing cluster. Finally, privacy and poisoning conclusions remain limited to the registered attacks and five seeds. These constraints support bounded protocol-level claims. Clinical and production-security validation remain future work.",
);

const after = await slide.export({ format: "png", scale: 2 });
await fs.writeFile(
  path.join(previewDir, "slide-34-after.png"),
  new Uint8Array(await after.arrayBuffer()),
);
const layout = await slide.export({ format: "layout" });
await fs.writeFile(path.join(previewDir, "slide-34-after.layout.json"), await layout.text());

const candidatePath = path.join(
  stagingDir,
  "Board-11_Group-2_CAABC-FL_Final_Defense_Limitations_v5_candidate.pptx",
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
    referenceSha256: "290f96d00b8187afb78310e249437400a6b89f1f630302a885ead16360ca7cbc",
  },
  verifyArtifactToolImport: true,
  receiptPath: path.join(
    stagingDir,
    "Board-11_Group-2_CAABC-FL_Final_Defense_Limitations_v5.validation.json",
  ),
});

console.log(JSON.stringify({ finalPath, slideCount: presentation.slides.items.length, result }, null, 2));
