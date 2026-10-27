import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = "E:/PrivacyPreserving-Healthcare-FL";
const sourcePath = path.join(workspaceDir, "output/presentation/CAABC-FL_Final_Defense_Fall_2025_Ready.pptx");
const finalPath = path.join(workspaceDir, "output/presentation/CAABC-FL_Final_Defense_25_September_2026_Final_v2.pptx");
const stagingDir = path.join(workspaceDir, ".codex-finalizer");
const skillDir = "C:/Users/HP/.codex/plugins/cache/openai-primary-runtime/presentations/26.909.12148/skills/presentations";
const runtimePython = "C:/Users/HP/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe";
const footerDate = "25 September 2026";

const { finalizePresentation } = await import(
  pathToFileURL(path.join(skillDir, "container_tools/artifact_tool_utils.mjs")).href,
);

await fs.mkdir(stagingDir, { recursive: true });
await fs.mkdir(path.dirname(finalPath), { recursive: true });

const presentation = await PresentationFile.importPptx(await FileBlob.load(sourcePath));
const snapshot = await presentation.inspect({
  kind: "textbox",
  include: "id,slide,text,bbox",
  maxChars: 120000,
});

let updatedCount = 0;
for (const line of snapshot.ndjson.split("\n").filter(Boolean)) {
  const record = JSON.parse(line);
  const [left, top] = record.bbox ?? [0, 0, 0, 0];
  if (left < 240 && top > 640 && String(record.text ?? "").trim() === "Fall 2025") {
    const dateShape = presentation.resolve(record.id);
    dateShape.text = "";
    const visibleDate = presentation.slides.getItem(record.slide - 1).shapes.add({
      geometry: "textbox",
      name: `visible-footer-date-${record.slide}`,
      position: { left: 49, top: 670, width: 190, height: 22 },
      fill: "none",
      line: { fill: "none", width: 0 },
    });
    visibleDate.text = footerDate;
    visibleDate.text.style = {
      typeface: "Arial",
      fontSize: 11,
      color: "#17365D",
      alignment: "left",
      verticalAlignment: "middle",
      autoFit: "shrinkText",
    };
    visibleDate.bringToFront();
    updatedCount += 1;
  }
}

if (updatedCount !== 31) {
  throw new Error(`Expected to update 31 footer dates, but updated ${updatedCount}`);
}

const candidatePath = path.join(stagingDir, "CAABC-FL_Final_Defense_25_September_2026_Final_v2_candidate.pptx");
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
  materializeLiteralChartWorkbooks: true,
  nativeChartTargetApplication: "powerpoint",
  fontPolicy: {
    basis: "reference",
    families: ["Arial", "Corbel"],
    referencePath: sourcePath,
    referenceSha256: "c427100573620d6960b3b2d9c098c3dc5cd9904a8f7442f087aa7cbbc98ac77b",
  },
  verifyArtifactToolImport: true,
  receiptPath: path.join(stagingDir, "CAABC-FL_Final_Defense_25_September_2026_Final_v2.validation.json"),
});

console.log(JSON.stringify({ finalPath, updatedCount, result }, null, 2));
