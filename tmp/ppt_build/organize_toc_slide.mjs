import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = "E:/PrivacyPreserving-Healthcare-FL";
const sourcePath = path.join(
  workspaceDir,
  "output/presentation/CAABC-FL_Final_Defense_25_September_2026_Problem_Formulation_Explained.pptx",
);
const finalPath = path.join(
  workspaceDir,
  "output/presentation/CAABC-FL_Final_Defense_25_September_2026_Organized_TOC.pptx",
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
const slide = presentation.slides.getItem(1);

const FONT = "Arial";
const NAVY = "#0B2C6B";
const GREEN = "#008A46";
const SUBTEXT = "#163F7A";
const MUTED = "#5B677A";
const LIGHT = "#DDE8E1";

slide.shapes.add({
  geometry: "rect",
  name: "toc-layout-cover",
  position: { left: 40, top: 120, width: 1200, height: 535 },
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
    fontSize: 18,
    color: NAVY,
    verticalAlignment: "middle",
    autoFit: "shrinkText",
    ...style,
  };
  return shape;
}

function addSection({ key, x, y, title, items = [], compact = false }) {
  slide.shapes.add({
    geometry: "rect",
    name: `${key}-marker`,
    position: { left: x, top: y + 7, width: 14, height: 14 },
    fill: "#FFFFFF",
    line: { fill: GREEN, width: 1.6 },
  });
  addText(`${key}-title`, title, { left: x + 28, top: y, width: 490, height: 31 }, {
    fontSize: compact ? 22 : 24,
    bold: true,
    color: "#111111",
  });

  const rowHeight = compact ? 23 : 27;
  items.forEach((item, index) => {
    const itemY = y + 36 + index * rowHeight;
    addText(`${key}-chevron-${index + 1}`, "›", { left: x + 42, top: itemY, width: 22, height: rowHeight }, {
      fontSize: 25,
      bold: true,
      color: GREEN,
      alignment: "center",
    });
    addText(`${key}-item-${index + 1}`, item, { left: x + 72, top: itemY, width: 430, height: rowHeight }, {
      fontSize: compact ? 16 : 17,
      color: SUBTEXT,
    });
  });
}

slide.shapes.add({
  geometry: "rect",
  name: "toc-center-divider",
  position: { left: 638, top: 150, width: 2, height: 470 },
  fill: LIGHT,
  line: { fill: "none", width: 0 },
});

slide.shapes.add({
  geometry: "rect",
  name: "toc-center-divider-accent",
  position: { left: 638, top: 230, width: 2, height: 305 },
  fill: GREEN,
  line: { fill: "none", width: 0 },
});

addSection({
  key: "toc-introduction",
  x: 82,
  y: 145,
  title: "Introduction",
  items: [
    "Background and motivation",
    "Problem statement",
    "Research questions and objectives",
  ],
});

addSection({
  key: "toc-literature",
  x: 82,
  y: 290,
  title: "Literature Review",
  items: [
    "Related studies",
    "Comparative analysis and research gap",
  ],
});

addSection({
  key: "toc-framework",
  x: 82,
  y: 405,
  title: "Conceptual Framework",
  items: [
    "Security goals and system components",
    "Threat model and trust assumptions",
  ],
});

addSection({
  key: "toc-methodology",
  x: 685,
  y: 145,
  title: "Proposed Methodology",
  items: [
    "System architecture",
    "CAABC-FL compression workflow",
    "Secure aggregation and governance",
  ],
});

addSection({
  key: "toc-results",
  x: 685,
  y: 290,
  title: "Results and Discussion",
  items: [
    "Utility and SOTA comparison",
    "Privacy and poisoning evaluation",
    "Communication and system overhead",
  ],
  compact: true,
});

addSection({
  key: "toc-conclusion",
  x: 685,
  y: 430,
  title: "Conclusion",
  items: [
    "Key findings",
    "Limitations and future work",
  ],
  compact: true,
});

addSection({
  key: "toc-references",
  x: 685,
  y: 550,
  title: "References",
  items: [],
  compact: true,
});

addSection({
  key: "toc-qa",
  x: 685,
  y: 592,
  title: "Question and Answer Session",
  items: [],
  compact: true,
});

addText(
  "toc-reading-order-note",
  "The presentation follows the thesis structure from problem definition to evidence and conclusions.",
  { left: 105, top: 545, width: 450, height: 55 },
  { fontSize: 15, italic: true, color: MUTED, verticalAlignment: "top" },
);

slide.speakerNotes.textFrame.setText(
  "The presentation begins with the research context, problem statement, research questions, and objectives. It then reviews related studies and the identified gap before presenting the conceptual framework and proposed methodology. The final part reports utility, privacy, robustness, communication, and system results, followed by the conclusion, references, and the question-and-answer session.",
);

const candidatePath = path.join(
  stagingDir,
  "CAABC-FL_Final_Defense_25_September_2026_Organized_TOC_candidate.pptx",
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
    referenceSha256: "6dc0b40f44cab8291b78173388768286bda42b4761609ccc921b2d64cb97db69",
  },
  verifyArtifactToolImport: true,
  receiptPath: path.join(
    stagingDir,
    "CAABC-FL_Final_Defense_25_September_2026_Organized_TOC.validation.json",
  ),
});

console.log(JSON.stringify({ finalPath, slideCount: presentation.slides.items.length, result }, null, 2));
