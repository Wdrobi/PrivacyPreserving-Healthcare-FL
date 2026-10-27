import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = "E:/PrivacyPreserving-Healthcare-FL";
const sourcePath = path.join(workspaceDir, "output/presentation/CAABC-FL_Final_Defense_25_September_2026_Final_v2.pptx");
const backgroundPath = path.join(workspaceDir, "output/presentation/assets/caabc_fl_title_background_v2.png");
const finalPath = path.join(workspaceDir, "output/presentation/CAABC-FL_Final_Defense_25_September_2026_Title_Background.pptx");
const stagingDir = path.join(workspaceDir, ".codex-finalizer");
const skillDir = "C:/Users/HP/.codex/plugins/cache/openai-primary-runtime/presentations/26.909.12148/skills/presentations";
const runtimePython = "C:/Users/HP/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe";

const { finalizePresentation } = await import(
  pathToFileURL(path.join(skillDir, "container_tools/artifact_tool_utils.mjs")).href,
);

await fs.mkdir(stagingDir, { recursive: true });
await fs.mkdir(path.dirname(finalPath), { recursive: true });

const presentation = await PresentationFile.importPptx(await FileBlob.load(sourcePath));
const imageSnapshot = await presentation.inspect({
  kind: "image",
  include: "id,slide,name,bbox",
  maxChars: 20000,
});

const titleImages = imageSnapshot.ndjson
  .split("\n")
  .filter(Boolean)
  .map((line) => JSON.parse(line))
  .filter((record) => record.slide === 1);

const backgroundRecord = titleImages.find((record) => {
  const [, , width = 0, height = 0] = record.bbox ?? [];
  return width > 1000 && height > 600;
});

if (!backgroundRecord) {
  throw new Error("Could not identify the title-slide background image.");
}

const backgroundImage = presentation.resolve(backgroundRecord.id);
const originalFrame = backgroundImage.frame;
const originalGeometry = backgroundImage.geometry;
const originalBorderRadius = backgroundImage.borderRadius;
const originalRotation = backgroundImage.rotation;
const originalFlipHorizontal = backgroundImage.flipHorizontal;
const originalFlipVertical = backgroundImage.flipVertical;
const originalLockAspectRatio = backgroundImage.lockAspectRatio;
const backgroundBytes = await fs.readFile(backgroundPath);

backgroundImage.replace({
  blob: backgroundBytes,
  contentType: "image/png",
  alt: "Connected healthcare institutions collaborating through encrypted federated learning",
  fit: "cover",
  prompt: "A clean academic healthcare cybersecurity background with hospitals connected to an encrypted federated-learning shield, composed for a thesis title slide.",
});
backgroundImage.frame = originalFrame;
backgroundImage.crop = { left: 0, top: 0, right: 0, bottom: 0 };
backgroundImage.geometry = originalGeometry;
backgroundImage.borderRadius = originalBorderRadius;
backgroundImage.rotation = originalRotation;
backgroundImage.flipHorizontal = originalFlipHorizontal;
backgroundImage.flipVertical = originalFlipVertical;
backgroundImage.lockAspectRatio = originalLockAspectRatio;

const candidatePath = path.join(stagingDir, "CAABC-FL_Final_Defense_25_September_2026_Title_Background_candidate.pptx");
await (await PresentationFile.exportPptx(presentation)).save(candidatePath);

const tableOwners = [9, 10, 11, 18, 21];
const result = await finalizePresentation({
  explicitTotalSlideCount: 31,
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
  requiredNativeChartOwnerSlides: [21],
  nativeChartTargetApplication: "powerpoint",
  fontPolicy: {
    basis: "reference",
    families: ["Arial", "Corbel"],
    referencePath: sourcePath,
    referenceSha256: "7783276c87bbc48c7b94efd81d4fc25d2bb5482f4d5a64e77e9a590116095a51",
  },
  verifyArtifactToolImport: true,
  receiptPath: path.join(stagingDir, "CAABC-FL_Final_Defense_25_September_2026_Title_Background.validation.json"),
});

console.log(JSON.stringify({ finalPath, backgroundImageId: backgroundRecord.id, result }, null, 2));
