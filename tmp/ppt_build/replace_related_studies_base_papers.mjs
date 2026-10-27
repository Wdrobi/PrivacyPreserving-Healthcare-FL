import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = "E:/PrivacyPreserving-Healthcare-FL";
const sourcePath = path.join(
  workspaceDir,
  "output/presentation/CAABC-FL_Final_Defense_25_September_2026_Problem_Paragraph_Reviewed.pptx",
);
const finalPath = path.join(
  workspaceDir,
  "output/presentation/CAABC-FL_Final_Defense_25_September_2026_Related_Studies_Final.pptx",
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

const C = {
  navy: "#062B6F",
  blue: "#1E3A5F",
  green: "#008A46",
  greenLight: "#EAF7F0",
  cyanLight: "#EAF4F8",
  amber: "#D97706",
  amberLight: "#FFF4E5",
  red: "#B42318",
  redLight: "#FFF0EE",
  ink: "#1F2937",
  muted: "#52606D",
  line: "#B7C1CC",
  white: "#FFFFFF",
};

function addText(slide, name, text, position, style = {}) {
  const item = slide.shapes.add({
    geometry: "textbox",
    name,
    position,
    fill: "none",
    line: { fill: "none", width: 0 },
  });
  item.text = text;
  item.text.style = {
    typeface: "Arial",
    fontSize: 18,
    color: C.ink,
    alignment: "left",
    verticalAlignment: "top",
    autoFit: "shrinkText",
    ...style,
  };
  return item;
}

function addBox(slide, name, text, position, { fill = C.cyanLight, line = C.blue, color = C.blue, fontSize = 17 } = {}) {
  const item = slide.shapes.add({
    geometry: "rect",
    name,
    position,
    fill,
    line: { fill: line, width: 1.4 },
  });
  item.text = text;
  item.text.style = {
    typeface: "Arial",
    fontSize,
    bold: true,
    color,
    alignment: "center",
    verticalAlignment: "middle",
    autoFit: "shrinkText",
  };
  return item;
}

function addArrowText(slide, name, glyph, position, { color = C.green, fontSize = 24 } = {}) {
  return addText(slide, name, glyph, position, {
    fontSize,
    bold: true,
    color,
    alignment: "center",
    verticalAlignment: "middle",
  });
}

function addBulletBlock(slide, prefix, heading, headingColor, bullets, top) {
  const headingShape = slide.shapes.add({
    geometry: "rect",
    name: `${prefix}-heading`,
    position: { left: 68, top, width: 690, height: 34 },
    fill: headingColor === C.green ? C.greenLight : C.redLight,
    line: { fill: headingColor, width: 1.1 },
  });
  headingShape.text = heading;
  headingShape.text.style = {
    typeface: "Arial",
    fontSize: 22,
    bold: true,
    color: headingColor,
    alignment: "left",
    verticalAlignment: "middle",
    autoFit: "shrinkText",
  };
  addText(
    slide,
    `${prefix}-bullets`,
    bullets.map((value) => `•  ${value}`).join("\n"),
    { left: 92, top: top + 37, width: 675, height: 106 },
    { fontSize: 18.5, color: C.ink, verticalAlignment: "top", autoFit: "shrinkText" },
  );
}

function prepareSlide(slide, page, title, paperTitle, summary, sourceLine) {
  if (page === 2) {
    slide.placeholders.getItem("title")?.delete();
    // Slide 12 was built with custom chrome; redraw only its title band.
    slide.shapes.add({
      geometry: "rect",
      name: `related-study-title-cover-${page}`,
      position: { left: 160, top: 0, width: 880, height: 112 },
      fill: C.white,
      line: { fill: "none", width: 0 },
    });
    slide.shapes.add({
      geometry: "rect",
      name: `related-study-top-rule-${page}`,
      position: { left: 30, top: 31, width: 1240, height: 1 },
      fill: "#222222",
      line: { fill: "none", width: 0 },
    });
    const titleShape = slide.shapes.add({
      geometry: "rect",
      name: `related-study-title-${page}`,
      position: { left: 210, top: 36, width: 820, height: 66 },
      fill: C.white,
      line: { fill: "none", width: 0 },
    });
    titleShape.text = title;
    titleShape.text.style = {
      typeface: "Arial",
      fontSize: 44,
      bold: true,
      color: C.navy,
      alignment: "center",
      verticalAlignment: "middle",
      autoFit: "shrinkText",
    };
  }

  // Hide the previous comparison table while preserving the university template chrome.
  slide.shapes.add({
    geometry: "rect",
    name: `related-study-cover-${page}`,
    position: { left: 45, top: 112, width: 1190, height: 535 },
    fill: C.white,
    line: { fill: "none", width: 0 },
  });

  addText(slide, `paper-title-${page}`, paperTitle, { left: 70, top: 118, width: 1140, height: 58 }, {
    fontSize: 24,
    bold: true,
    color: C.green,
    alignment: "center",
    verticalAlignment: "middle",
  });
  addText(slide, `paper-summary-${page}`, summary, { left: 70, top: 180, width: 690, height: 78 }, {
    fontSize: 19,
    color: C.ink,
    verticalAlignment: "middle",
  });
  addText(slide, `paper-source-${page}`, sourceLine, { left: 70, top: 612, width: 1140, height: 28 }, {
    fontSize: 13.5,
    italic: true,
    color: C.muted,
    alignment: "center",
    verticalAlignment: "middle",
  });
}

// Slide 11 — DDFed.
{
  const slide = presentation.slides.getItem(10);
  prepareSlide(
    slide,
    1,
    "Related Studies (1/3)",
    "Dual Defense: Enhancing Privacy and Mitigating Poisoning Attacks in Federated Learning [16]",
    "DDFed combines fully homomorphic encryption with a two-phase anomaly detector so that protected updates can be screened before aggregation under both cross-device and cross-silo settings.",
    "Source: Xu et al., NeurIPS 2024 [16].",
  );
  addBulletBlock(slide, "ddfed-strengths", "Strengths", C.green, [
    "Addresses update confidentiality and model poisoning in one framework.",
    "Uses secure similarity analysis and collaborative anomaly selection.",
    "Evaluates multiple poisoning attacks across two FL settings.",
  ], 272);
  addBulletBlock(slide, "ddfed-limits", "Limitations relative to this thesis", C.red, [
    "Does not provide a formal record-level differential-privacy guarantee.",
    "Its FHE and anomaly pipeline differs from a sum-only CKKS workflow.",
    "No ciphertext-aligned adaptive compression or external audit layer.",
  ], 430);

  addText(slide, "ddfed-flow-title", "DDFed conceptual workflow", { left: 820, top: 188, width: 365, height: 32 }, {
    fontSize: 20,
    bold: true,
    color: C.blue,
    alignment: "center",
  });
  const x = 855;
  const w = 295;
  addBox(slide, "ddfed-box-1", "Hospitals train locally", { left: x, top: 230, width: w, height: 50 }, { fill: C.cyanLight });
  addArrowText(slide, "ddfed-arrow-1", "↓", { left: 955, top: 280, width: 95, height: 28 });
  addBox(slide, "ddfed-box-2", "FHE-encrypted updates", { left: x, top: 308, width: w, height: 50 }, { fill: C.greenLight, line: C.green, color: C.green });
  addArrowText(slide, "ddfed-arrow-2", "↓", { left: 955, top: 358, width: 95, height: 28 });
  addBox(slide, "ddfed-box-3", "Secure similarity + anomaly selection", { left: x, top: 386, width: w, height: 62 }, { fill: C.amberLight, line: C.amber, color: C.amber, fontSize: 16 });
  addArrowText(slide, "ddfed-arrow-3", "↓", { left: 955, top: 448, width: 95, height: 28 });
  addBox(slide, "ddfed-box-4", "Accepted global update", { left: x, top: 476, width: w, height: 52 }, { fill: C.greenLight, line: C.green, color: C.green });
  addText(slide, "ddfed-diagram-caption", "Privacy and anomaly detection are co-designed [16].", { left: 820, top: 542, width: 365, height: 42 }, {
    fontSize: 15,
    italic: true,
    color: C.muted,
    alignment: "center",
    verticalAlignment: "middle",
  });
  slide.speakerNotes.textFrame.setText(
    "DDFed is one of the closest integrated studies because it addresses both privacy and poisoning. It uses fully homomorphic encryption and a two-phase anomaly detector based on secure similarity computation and feedback-driven collaborative selection. Its experiments cover model-poisoning attacks in cross-device and cross-silo federated learning. Relative to this thesis, DDFed does not provide record-level differential privacy, ciphertext-aligned adaptive compression, threshold-governed release, or an external permissioned audit trail. Source: https://proceedings.neurips.cc/paper_files/paper/2024/hash/824f98c4e9bb301b0b96fa2ae071360b-Abstract-Conference.html",
  );
}

// Slide 12 — DP-BREM / DP-BREM+.
{
  const slide = presentation.slides.getItem(11);
  slide.shapes.getItem("chrome-title-10")?.delete();
  prepareSlide(
    slide,
    2,
    "Related Studies (2/3)",
    "DP-BREM: Differentially-Private and Byzantine-Robust Federated Learning with Client Momentum [17]",
    "DP-BREM learns from client history: momentum reduces honest-update variance and exposes small malicious perturbations. DP-BREM+ removes the trusted-server assumption through secure aggregation and jointly generated noise.",
    "Source: Gu, Li, and Xiong, USENIX Security 2025 [17].",
  );
  addBulletBlock(slide, "dpbrem-strengths", "Strengths", C.green, [
    "Combines formal differential privacy with Byzantine robustness.",
    "Uses longitudinal client momentum rather than one-round evidence only.",
    "DP-BREM+ protects updates and distributes DP-noise generation.",
  ], 272);
  addBulletBlock(slide, "dpbrem-limits", "Limitations relative to this thesis", C.red, [
    "No cryptography-aware method for reducing encrypted wire payload.",
    "Robustness depends on client history and the stated Byzantine model.",
    "No clinical cohort, independent verifier, or external audit ledger.",
  ], 430);

  addText(slide, "dpbrem-flow-title", "DP-BREM+ conceptual workflow", { left: 820, top: 188, width: 365, height: 32 }, {
    fontSize: 20,
    bold: true,
    color: C.blue,
    alignment: "center",
  });
  const x = 855;
  const w = 295;
  addBox(slide, "dpbrem-box-1", "Current client update", { left: x, top: 230, width: w, height: 50 }, { fill: C.cyanLight });
  addArrowText(slide, "dpbrem-arrow-1", "+ history ↓", { left: 930, top: 280, width: 145, height: 28 }, { fontSize: 19 });
  addBox(slide, "dpbrem-box-2", "Client momentum", { left: x, top: 308, width: w, height: 50 }, { fill: C.amberLight, line: C.amber, color: C.amber });
  addArrowText(slide, "dpbrem-arrow-2", "↓", { left: 955, top: 358, width: 95, height: 28 });
  addBox(slide, "dpbrem-box-3", "Secure aggregation + jointly generated DP noise", { left: x, top: 386, width: w, height: 62 }, { fill: C.greenLight, line: C.green, color: C.green, fontSize: 16 });
  addArrowText(slide, "dpbrem-arrow-3", "↓", { left: 955, top: 448, width: 95, height: 28 });
  addBox(slide, "dpbrem-box-4", "Private, robust global model", { left: x, top: 476, width: w, height: 52 }, { fill: C.greenLight, line: C.green, color: C.green });
  addText(slide, "dpbrem-diagram-caption", "History, privacy, and robustness are linked [17].", { left: 820, top: 542, width: 365, height: 42 }, {
    fontSize: 15,
    italic: true,
    color: C.muted,
    alignment: "center",
    verticalAlignment: "middle",
  });
  slide.speakerNotes.textFrame.setText(
    "DP-BREM and DP-BREM+ jointly address differential privacy and Byzantine robustness in cross-silo federated learning. Client momentum averages each client's updates over time, reducing honest-client variance and making accumulated malicious perturbations easier to detect. DP-BREM assumes a trusted server; DP-BREM+ removes that assumption with secure aggregation and client-generated distributed noise. Relative to this thesis, it does not address ciphertext-aware adaptive compression, healthcare deployment evidence, independently verified aggregation, or external audit logging. Source: https://www.usenix.org/conference/usenixsecurity25/presentation/gu-xiaolan",
  );
}

// Slide 13 — PREAMBLE.
{
  const slide = presentation.slides.getItem(12);
  prepareSlide(
    slide,
    3,
    "Related Studies (3/3)",
    "PREAMBLE: Private and Efficient Aggregation via Block Sparse Vectors [18]",
    "PREAMBLE co-designs a two-server private-aggregation protocol with block-sparse vectors, distributed point functions, sampling, and privacy amplification to reduce high-dimensional communication.",
    "Source: Asi et al., NeurIPS 2025 [18].",
  );
  addBulletBlock(slide, "preamble-strengths", "Strengths", C.green, [
    "Aligns the sparse representation with its protected transport protocol.",
    "Reduces communication and computation for block-sparse vectors.",
    "Provides formal privacy–utility analysis with low added noise overhead.",
  ], 272);
  addBulletBlock(slide, "preamble-limits", "Limitations relative to this thesis", C.red, [
    "Requires two non-colluding aggregation servers.",
    "Targets vector aggregation rather than iterative CKKS clinical FL.",
    "Does not evaluate poisoning, release governance, or healthcare utility.",
  ], 430);

  addText(slide, "preamble-flow-title", "PREAMBLE conceptual workflow", { left: 820, top: 188, width: 365, height: 32 }, {
    fontSize: 20,
    bold: true,
    color: C.blue,
    alignment: "center",
  });
  addBox(slide, "preamble-box-1", "Block-sparse client vector", { left: 855, top: 230, width: 295, height: 52 }, { fill: C.cyanLight });
  addArrowText(slide, "preamble-arrow-split", "↙                 ↘", { left: 865, top: 282, width: 275, height: 34 }, { fontSize: 25 });
  addBox(slide, "preamble-box-2a", "Server A\nDPF share", { left: 825, top: 322, width: 165, height: 78 }, { fill: C.greenLight, line: C.green, color: C.green, fontSize: 17 });
  addBox(slide, "preamble-box-2b", "Server B\nDPF share", { left: 1015, top: 322, width: 165, height: 78 }, { fill: C.greenLight, line: C.green, color: C.green, fontSize: 17 });
  addArrowText(slide, "preamble-arrow-merge", "↘                 ↙", { left: 865, top: 402, width: 275, height: 34 }, { fontSize: 25 });
  addBox(slide, "preamble-box-3", "Private block-sparse aggregate", { left: 855, top: 446, width: 295, height: 62 }, { fill: C.amberLight, line: C.amber, color: C.amber, fontSize: 16 });
  addText(slide, "preamble-diagram-caption", "Efficiency relies on a two-server non-collusion model [18].", { left: 815, top: 530, width: 375, height: 54 }, {
    fontSize: 15,
    italic: true,
    color: C.muted,
    alignment: "center",
    verticalAlignment: "middle",
  });
  slide.speakerNotes.textFrame.setText(
    "PREAMBLE addresses private aggregation of high-dimensional vectors in a two-server architecture. It uses block-sparse distributed point functions, random sampling, and privacy amplification so that communication and computation depend more strongly on active blocks than on the full vector dimension. Its formal analysis is a strong example of co-designing representation and privacy transport. Relative to this thesis, PREAMBLE assumes two non-colluding servers, targets private vector aggregation rather than iterative CKKS healthcare training, and does not study poisoning or release governance. Source: https://proceedings.neurips.cc/paper_files/paper/2025/hash/1d3c1c0bade7b2b1974d3120ab6232b0-Abstract-Conference.html",
  );
}

const candidatePath = path.join(
  stagingDir,
  "CAABC-FL_Final_Defense_25_September_2026_Base_Papers_Reviewed_candidate.pptx",
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
  materializeLiteralChartWorkbooks: true,
  nativeChartTargetApplication: "powerpoint",
  fontPolicy: {
    basis: "reference",
    families: ["Arial", "Corbel"],
    referencePath: sourcePath,
    referenceSha256: "83f580d74c54326c9fcbf10bce5b24b93709b1d66088985904d8f0f0880656aa",
  },
  verifyArtifactToolImport: true,
  receiptPath: path.join(
    stagingDir,
    "CAABC-FL_Final_Defense_25_September_2026_Related_Studies_Final.validation.json",
  ),
});

console.log(JSON.stringify({ finalPath, result }, null, 2));
