import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = "E:/PrivacyPreserving-Healthcare-FL";
const sourcePath = "E:/Download/Final Defence Thesis-Project Presentation Slide For Spring 2025.pptx";
const skillDir = "C:/Users/HP/.codex/plugins/cache/openai-primary-runtime/presentations/26.909.12148/skills/presentations";
const runtimePython = "C:/Users/HP/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe";
const buildDir = path.join(workspaceDir, "tmp/ppt_build");
const finalPath = path.join(workspaceDir, "output/presentation/CAABC-FL_Final_Defense_Fall_2025_Ready.pptx");
const stagingDir = path.join(workspaceDir, ".codex-finalizer");
const titleText = "CAABC-FL: A Hybrid Privacy-Preserving Framework for Secure Multi-Institutional Collaboration";
const shortFooter = "CAABC-FL: A Hybrid Privacy-Preserving Framework for Secure Multi-Institutional Collaboration";
const FONT = "Arial";
const BLUE = "#17365D";
const CYAN = "#00AEEF";
const GREEN = "#00843D";
const LIGHT_GREEN = "#E8F3EC";
const LIGHT_BLUE = "#EAF2F8";
const ORANGE = "#F4B183";
const RED = "#C00000";
const TEXT = "#1F2937";
const MUTED = "#5B6573";
const BORDER = "#B8C4CE";

const { makeNativeBulletParagraphs, applyPresentationChartFont, finalizePresentation } = await import(
  pathToFileURL(path.join(skillDir, "container_tools/artifact_tool_utils.mjs")).href,
);

await fs.mkdir(buildDir, { recursive: true });
await fs.mkdir(path.dirname(finalPath), { recursive: true });
await fs.mkdir(stagingDir, { recursive: true });

const presentation = await PresentationFile.importPptx(await FileBlob.load(sourcePath));

// The first three slides contain template instructions.  The title slide and
// thesis range begin at source slide 4.
for (let i = 0; i < 3; i += 1) presentation.slides.getItem(0).delete();

// Several template slides contain legacy native tables whose imported cells
// are not individually deletable. Replace those slides with duplicates of an
// adjacent clean content layout before taking the snapshot, then populate the
// replacements below. This prevents hidden/overlaid table geometry.
const cleanContentLayout = presentation.slides.getItem(16);
for (const slideIndex of [8, 9, 10, 17]) {
  const legacySlide = presentation.slides.getItem(slideIndex);
  const replacementSlide = cleanContentLayout.duplicate();
  replacementSlide.moveTo(slideIndex);
  legacySlide.delete();
}

const slideTitles = [
  null,
  "Table of Contents",
  "Introduction",
  "Background",
  "Problem Statement",
  "Motivation",
  "Research Objectives",
  "Literature Review",
  "Related Studies (1/3)",
  "Related Studies (2/3)",
  "Related Studies (3/3)",
  "Research Gap",
  "Proposed Methodology",
  "System Approach",
  "Research Design",
  "Data Collection Methods",
  "Data Analysis Methods",
  "Budget Plan",
  "Results and Discussion",
  "Key Findings",
  "Same-Protocol Comparison",
  "Privacy, Poisoning and Systems Performance",
  "Conclusion",
  "Summary of Key Findings",
  "Research Contributions",
  "Limitations",
  "Future Work",
  "References (1/2)",
  "References (2/2)",
  "Q&A Session",
  "Thank You",
];

const snapshot = await presentation.inspect({
  kind: "slide,textbox,shape,image,table,chart",
  include: "id,slide,name,text,textPreview,bbox,bboxUnit",
  maxChars: 150000,
});
const records = snapshot.ndjson
  .split("\n")
  .filter(Boolean)
  .map((line) => JSON.parse(line));

const bySlide = (slideNumber, kinds = null) => records.filter(
  (record) => record.slide === slideNumber && (!kinds || kinds.includes(record.kind)),
);

function safeDelete(id) {
  try {
    presentation.resolve(id).delete();
  } catch {
    // Some imported layout-owned objects are not independently deletable.
  }
}

function clearContent(slideNumber) {
  for (const record of bySlide(slideNumber)) {
    if (["table", "chart"].includes(record.kind)) {
      safeDelete(record.id);
      continue;
    }
    const bbox = record.bbox ?? [0, 0, 0, 0];
    const [left, top] = bbox;
    if (record.kind === "textbox") {
      const keepHeader = top < 115;
      const keepFooter = top > 630;
      if (!keepHeader && !keepFooter) safeDelete(record.id);
    } else if (record.kind === "image") {
      const keepLogo = top < 120 && (left < 170 || left > 980);
      if (!keepLogo) safeDelete(record.id);
    }
  }
}

function updateTemplateText() {
  for (const record of records.filter((item) => item.kind === "textbox")) {
    const target = presentation.resolve(record.id);
    const [left, top] = record.bbox ?? [0, 0, 0, 0];
    if (record.slide === 1) continue;
    if (top > 675 && left > 230 && left < 1050) {
      target.text = shortFooter;
    } else if (top > 640 && left < 240) {
      target.text = "Fall 2025";
    } else if (top > 620 && left > 1100) {
      target.text = String(record.slide);
    }
  }
  for (let slideNumber = 2; slideNumber <= 31; slideNumber += 1) {
    const titleRecord = bySlide(slideNumber, ["textbox"]).find((record) => {
      const [, top] = record.bbox ?? [0, 999];
      return top < 115 && (record.text ?? "").trim().length > 0 && !String(record.text).includes("2025");
    });
    if (titleRecord && slideTitles[slideNumber - 1]) {
      const titleShape = presentation.resolve(titleRecord.id);
      titleShape.text = slideTitles[slideNumber - 1];
      const [left, , width, height] = titleRecord.bbox ?? [180, 18, 920, 82];
      titleShape.frame = { left, top: 18, width, height };
    }
  }
}

function addText(slide, name, text, position, options = {}) {
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
    fontSize: options.fontSize ?? 27,
    bold: options.bold ?? false,
    italic: options.italic ?? false,
    color: options.color ?? TEXT,
    alignment: options.alignment ?? "left",
    verticalAlignment: options.verticalAlignment ?? "top",
    autoFit: options.autoFit ?? "shrinkText",
  };
  return shape;
}

function addBullets(slide, name, items, position, options = {}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    name,
    position,
    fill: "none",
    line: { fill: "none", width: 0 },
  });
  shape.text = makeNativeBulletParagraphs(items, {
    marginLeftPoints: options.marginLeftPoints ?? 20,
    hangingPoints: options.hangingPoints ?? 10,
    spaceAfterPoints: options.spaceAfterPoints ?? 10,
  });
  shape.text.style = {
    typeface: FONT,
    fontSize: options.fontSize ?? 27,
    color: options.color ?? TEXT,
    autoFit: "shrinkText",
  };
  return shape;
}

function addRule(slide, left, top, width, color = GREEN, height = 2) {
  return slide.shapes.add({
    geometry: "rect",
    name: `rule-${left}-${top}`,
    position: { left, top, width, height },
    fill: color,
    line: { fill: "none", width: 0 },
  });
}

async function addImage(slide, name, filePath, position, alt) {
  const bytes = new Uint8Array(await fs.readFile(filePath));
  return slide.images.add({
    blob: bytes,
    contentType: "image/png",
    alt,
    fit: "contain",
    position,
  });
}

async function rebuildContentSlide(slideNumber, title) {
  const slide = presentation.slides.getItem(slideNumber - 1);
  slide.shapes.deleteAll();
  for (const record of bySlide(slideNumber, ["image"])) safeDelete(record.id);
  slide.background.fill = "#FFFFFF";
  await addImage(slide, `cse-logo-${slideNumber}`, path.join(workspaceDir, "tmp/ppt_assets/image1.jpg"), { left: 38, top: 39, width: 72, height: 72 }, "Computer Science and Engineering emblem");
  await addImage(slide, `gub-logo-${slideNumber}`, path.join(workspaceDir, "tmp/ppt_assets/image2.png"), { left: 1041, top: 26, width: 204, height: 85 }, "Green University of Bangladesh logo");
  addText(slide, `chrome-title-${slideNumber}`, title, { left: 198, top: 27, width: 843, height: 85 }, { fontSize: 39, bold: true, color: BLUE, alignment: "center", verticalAlignment: "middle" });
  addRule(slide, 45, 665, 1190, "#C8D9A5", 1);
  addText(slide, `chrome-date-${slideNumber}`, "Fall 2025", { left: 49, top: 671, width: 150, height: 24 }, { fontSize: 12, color: BLUE, verticalAlignment: "middle" });
  addText(slide, `chrome-footer-${slideNumber}`, shortFooter, { left: 280, top: 684, width: 702, height: 24 }, { fontSize: 12, color: "#6B7280", alignment: "center", verticalAlignment: "middle" });
  addText(slide, `chrome-page-${slideNumber}`, String(slideNumber), { left: 1184, top: 643, width: 72, height: 52 }, { fontSize: 34, bold: true, color: BLUE, alignment: "center", verticalAlignment: "middle" });
}

function styleTable(table, rows, cols, options = {}) {
  table.borders.assign({ style: "solid", fill: BORDER, width: 1 });
  table.cells.block({ row: 0, column: 0, rowCount: rows, columnCount: cols }).assign({
    fill: "#FFFFFF",
    textStyle: { typeface: FONT, fontSize: options.fontSize ?? 18, color: TEXT },
    margins: { left: 7, right: 7, top: 5, bottom: 5 },
    anchor: "middle",
  });
  table.cells.block({ row: 0, column: 0, rowCount: 1, columnCount: cols }).assign({
    fill: BLUE,
    textStyle: { typeface: FONT, fontSize: options.headerFontSize ?? 18, color: "#FFFFFF", bold: true },
    anchor: "middle",
  });
  table.styleOptions = { headerRow: true, bandedRows: true };
}

function addNote(slide, text) {
  slide.speakerNotes.textFrame.setText(text);
  slide.speakerNotes.setVisible(true);
}

updateTemplateText();

// Three source slides contain grouped or table objects that cannot be removed
// reliably one object at a time. Rebuild their content layer while retaining
// the same university chrome, geometry, and 16:9 canvas.
await rebuildContentSlide(2, slideTitles[1]);
await rebuildContentSlide(10, slideTitles[9]);

// Title slide
{
  const titleSlide = presentation.slides.getItem(0);
  const titleRecord = bySlide(1, ["textbox"]).find((record) => String(record.text).includes("Replace By Your Title"));
  const subtitleRecord = bySlide(1, ["textbox"]).find((record) => String(record.text).includes("Thesis Final_Defense"));
  const presenterRecord = bySlide(1, ["textbox"]).find((record) => String(record.text).includes("Presented By"));
  const dateRecord = bySlide(1, ["textbox"]).find((record) => String(record.text).includes("27 October 2025"));
  if (titleRecord) {
    const target = presentation.resolve(titleRecord.id);
    target.text = titleText;
    target.frame = { left: 80, top: 105, width: 1120, height: 145 };
    target.text.style = { typeface: FONT, fontSize: 39, bold: true, color: BLUE, alignment: "center", autoFit: "shrinkText" };
  }
  if (subtitleRecord) presentation.resolve(subtitleRecord.id).text = "Thesis Final Defense\nFall 2025";
  if (presenterRecord) {
    presentation.resolve(presenterRecord.id).text = [
      "Presented by",
      "Md. Robiul Islam - 222002068",
      "Ashrafun Nahar Arifa - 222002066",
      "Md. Atikur Rahman - 221902166",
    ].join("\n");
  }
  if (dateRecord) presentation.resolve(dateRecord.id).text = "Fall 2025";
  addNote(titleSlide, "Good morning. We are presenting CAABC-FL, a hybrid privacy-preserving framework for secure collaboration among healthcare institutions. Our work focuses on privacy, communication cost, poisoning resilience, and accountable model release.");
}

// Clear template instruction content while retaining template logos, titles, and footers.
const dividerSlides = new Set([3, 8, 13, 19, 23]);
for (let slideNumber = 2; slideNumber <= 29; slideNumber += 1) {
  if (!dividerSlides.has(slideNumber)) clearContent(slideNumber);
}

// Slide 2: Table of contents
{
  const slide = presentation.slides.getItem(1);
  addText(slide, "toc-left", "1  Introduction\n\n2  Literature Review\n\n3  Proposed Methodology", { left: 150, top: 165, width: 450, height: 330 }, { fontSize: 30, bold: true, color: BLUE });
  addRule(slide, 630, 150, 3, GREEN, 400);
  addText(slide, "toc-right", "4  Results and Discussion\n\n5  Conclusion\n\n6  References and Q&A", { left: 690, top: 165, width: 450, height: 330 }, { fontSize: 30, bold: true, color: BLUE });
  addNote(slide, "The presentation follows the thesis structure. We begin with the problem and prior work, explain the system and experimental protocol, then present the results, limitations, and conclusions.");
}

// Slide 3: Introduction divider
addNote(presentation.slides.getItem(2), "This section introduces the setting, the unresolved engineering problem, our motivation, and the three research objectives.");

// Slide 4: Background
{
  const slide = presentation.slides.getItem(3);
  addBullets(slide, "background-bullets", [
    "Hospitals hold complementary clinical data, but direct pooling increases privacy, ownership, and breach risks.",
    "Federated learning keeps source records local while hospitals contribute model updates to a shared training process [1]-[3].",
    "Model updates can still reveal membership or training features, and encryption increases communication cost [4]-[6].",
    "Recent systems combine privacy, secure aggregation, compression, or robustness, but usually evaluate these controls separately.",
  ], { left: 105, top: 145, width: 1070, height: 420 }, { fontSize: 27, spaceAfterPoints: 14 });
  addText(slide, "background-takeaway", "Research context: useful collaboration requires privacy controls that remain practical under encryption and adversarial participation.", { left: 130, top: 565, width: 1020, height: 70 }, { fontSize: 23, bold: true, color: GREEN, alignment: "center" });
  addNote(slide, "Federated learning reduces the need to exchange raw patient records, but it does not solve every privacy and integrity problem. This thesis studies the full training path, including update protection, encrypted transport, poisoning response, and release governance. Sources: McMahan et al. [1], Sheller et al. [2], Dayan et al. [3], Shokri et al. [4], Zhu et al. [5], and Geiping et al. [6].");
}

// Slide 5: Problem statement
{
  const slide = presentation.slides.getItem(4);
  addBullets(slide, "problem-bullets", [
    "Patient data remain local, yet gradients and model updates can leak sensitive information.",
    "CKKS aggregation hides update values but expands serialized payloads and blocks many plaintext poisoning defences.",
    "A central decryptor, unverified aggregation, and weak audit evidence concentrate trust in a small set of services.",
    "Existing studies rarely test utility, privacy attacks, poisoning, communication, and governance under one frozen protocol.",
  ], { left: 105, top: 145, width: 1070, height: 335 }, { fontSize: 27, spaceAfterPoints: 11 });
  const q = slide.shapes.add({ geometry: "roundRect", name: "research-question", position: { left: 120, top: 505, width: 1040, height: 105 }, fill: LIGHT_BLUE, line: { style: "solid", fill: CYAN, width: 2 } });
  q.text = "Research question\nHow can multiple institutions train a useful shared model while limiting privacy exposure, encrypted communication cost, poisoning damage, and unilateral control?";
  q.text.style = { typeface: FONT, fontSize: 23, bold: true, color: BLUE, alignment: "center", verticalAlignment: "middle", autoFit: "shrinkText" };
  addNote(slide, "The problem has four connected parts. Privacy mechanisms can hide information, but encryption makes communication expensive and removes the update geometry used by robust aggregators. Governance controls must also prevent one service from silently changing or releasing a model.");
}

// Slide 6: Motivation
{
  const slide = presentation.slides.getItem(5);
  const columns = [
    ["Clinical collaboration", "Use diverse hospital data without transferring source records."],
    ["Measurable privacy", "Combine formal differential privacy with empirical attack evaluation."],
    ["Encrypted efficiency", "Reduce real serialized ciphertext bytes, not only logical coordinates."],
    ["Accountable release", "Verify aggregation and record rollback, reputation, and audit evidence."],
  ];
  columns.forEach(([heading, body], index) => {
    const left = 85 + index * 292;
    addText(slide, `motivation-heading-${index}`, heading, { left, top: 175, width: 245, height: 70 }, { fontSize: 26, bold: true, color: index % 2 === 0 ? GREEN : BLUE, alignment: "center" });
    addRule(slide, left + 20, 255, 205, index % 2 === 0 ? GREEN : CYAN, 3);
    addText(slide, `motivation-body-${index}`, body, { left, top: 280, width: 245, height: 210 }, { fontSize: 23, alignment: "center", verticalAlignment: "middle" });
  });
  addText(slide, "motivation-close", "The thesis treats privacy, systems cost, adversarial resilience, and trust as one engineering problem.", { left: 175, top: 540, width: 930, height: 65 }, { fontSize: 25, bold: true, color: BLUE, alignment: "center" });
  addNote(slide, "We selected this topic because healthcare institutions need collaboration without unrestricted data sharing. The work also addresses a practical systems question: a compressor is valuable only when encrypted network bytes decrease and the model remains useful.");
}

// Slide 7: Objectives
{
  const slide = presentation.slides.getItem(6);
  const objectives = [
    ["1", "Design and implement", "a secure, privacy-preserving architecture for collaborative learning across institutions."],
    ["2", "Develop", "a communication-efficient method for protected model exchange while maintaining predictive utility."],
    ["3", "Evaluate", "the framework against relevant baselines under benign and adversarial conditions."],
  ];
  objectives.forEach(([number, verb, statement], index) => {
    const top = 155 + index * 150;
    const circle = slide.shapes.add({ geometry: "ellipse", name: `objective-${number}`, position: { left: 125, top, width: 82, height: 82 }, fill: index === 1 ? BLUE : GREEN, line: { fill: "none", width: 0 } });
    circle.text = number;
    circle.text.style = { typeface: FONT, fontSize: 32, bold: true, color: "#FFFFFF", alignment: "center", verticalAlignment: "middle" };
    addText(slide, `objective-text-${number}`, `${verb} ${statement}`, { left: 245, top: top - 5, width: 900, height: 100 }, { fontSize: 28, color: TEXT, verticalAlignment: "middle" });
  });
  addNote(slide, "The supervisor requested three concise objectives. The first covers the integrated architecture, the second covers the communication contribution, and the third covers comparative evaluation under normal and adversarial operation.");
}

// Slide 8: Literature review divider
addNote(presentation.slides.getItem(7), "The literature review groups prior work by healthcare collaboration, privacy and cryptography, communication reduction, and poisoning resilience.");

// Slide 9: Related studies 1
{
  const slide = presentation.slides.getItem(8);
  addText(slide, "table-caption-rs1", "TABLE I. Representative foundations for collaborative and private learning", { left: 150, top: 120, width: 980, height: 35 }, { fontSize: 18, italic: true, alignment: "center" });
  const values = [
    ["Study", "Focus", "Main contribution", "Limitation for this thesis"],
    ["FedAvg [1]", "Federated optimization", "Iterative training without centralizing data", "No privacy or poisoning control"],
    ["Sheller et al. [2]", "Healthcare FL", "Natural multi-institution collaboration", "Limited integrated security evidence"],
    ["FLDP [11]", "Private aggregation", "Efficient malicious-secure DP aggregation", "No poisoning layer"],
    ["FAMHE [12]", "Multiparty HE", "Protected biomedical analytics", "Communication and trust assumptions differ"],
  ];
  const table = slide.tables.add({ rows: values.length, columns: 4, left: 80, top: 170, width: 1120, height: 395, columnWidths: [190, 215, 345, 370], values });
  styleTable(table, values.length, 4, { fontSize: 17, headerFontSize: 18 });
  addText(slide, "rs1-note", "Prior work established feasibility, but each stream optimized a different part of the problem.", { left: 150, top: 585, width: 980, height: 45 }, { fontSize: 22, bold: true, color: GREEN, alignment: "center" });
  addNote(slide, "FedAvg provides the optimization baseline. Healthcare studies show that institutions can collaborate without pooling records. FLDP and FAMHE strengthen privacy, but they do not evaluate the complete privacy, compression, poisoning, and governance combination used in our protocol.");
}

// Slide 10: Related studies 2
{
  const slide = presentation.slides.getItem(9);
  addText(slide, "table-caption-rs2", "TABLE II. Communication and robustness methods", { left: 150, top: 120, width: 980, height: 35 }, { fontSize: 18, italic: true, alignment: "center" });
  const values = [
    ["Approach", "Privacy", "Communication", "Poisoning response", "Main assumption"],
    ["SoteriaFL [13]", "Formal DP", "Logical compression", "No", "Dense encryption can remove wire savings"],
    ["Fed-EF [14]", "No formal DP", "Error-feedback compression", "No", "Individual updates remain visible"],
    ["FLTrust [15]", "No", "No", "Trust-weighted aggregation", "Clean representative root data"],
    ["DDFed [16]", "Encrypted updates", "Secondary", "Encrypted anomaly detection", "FHE and anomaly model"],
  ];
  const table = slide.tables.add({ rows: values.length, columns: 5, left: 55, top: 170, width: 1170, height: 395, columnWidths: [185, 180, 205, 265, 335], values });
  styleTable(table, values.length, 5, { fontSize: 16, headerFontSize: 17 });
  addText(slide, "rs2-note", "Plaintext robust aggregation often conflicts with the update hiding provided by homomorphic aggregation.", { left: 135, top: 585, width: 1010, height: 45 }, { fontSize: 22, bold: true, color: BLUE, alignment: "center" });
  addNote(slide, "Communication and robustness methods expose a compatibility gap. Methods such as FLTrust depend on individual update geometry, while sum-only homomorphic aggregation hides that geometry. Logical sparsity also fails to save bandwidth if the system encodes a dense ciphertext afterward.");
}

// Slide 11: Related studies 3
{
  const slide = presentation.slides.getItem(10);
  addText(slide, "table-caption-rs3", "TABLE III. Capability map of recent integrated methods", { left: 150, top: 120, width: 980, height: 35 }, { fontSize: 18, italic: true, alignment: "center" });
  const values = [
    ["Method", "Healthcare evidence", "Formal DP", "Protected aggregation", "Wire-aware compression", "Poisoning defence"],
    ["FLDP [11]", "Limited", "Yes", "Yes", "Protocol-level", "No"],
    ["DDFed [16]", "Limited", "No", "Yes", "No", "Yes"],
    ["DP-BREM+ [17]", "Limited", "Yes", "Yes", "No", "Yes"],
    ["PREAMBLE [18]", "Different task", "Yes", "Yes", "Yes", "No"],
    ["CAABC-FL", "PhysioNet 2019", "Yes", "CKKS sum path", "Measured bytes", "Release control"],
  ];
  const table = slide.tables.add({ rows: values.length, columns: 6, left: 45, top: 165, width: 1190, height: 420, columnWidths: [160, 190, 135, 230, 225, 250], values });
  styleTable(table, values.length, 6, { fontSize: 15, headerFontSize: 15.5 });
  addText(slide, "rs3-note", "The rows use different datasets and threat models, so this map describes scope rather than rank.", { left: 150, top: 600, width: 980, height: 35 }, { fontSize: 20, italic: true, color: MUTED, alignment: "center" });
  addNote(slide, "Recent integrated methods cover more than one security objective, but their assumptions and evaluation units differ. Our comparison therefore reports capabilities and uses same-protocol reproduction for numerical results rather than comparing headline numbers from unrelated experiments.");
}

// Slide 12: Research gap
{
  const slide = presentation.slides.getItem(11);
  addBullets(slide, "gap-bullets", [
    "No reviewed study evaluates patient-level DP, real CKKS serialization, adaptive common-block compression, poisoning-aware release, and external audit evidence under one protocol.",
    "Many compressors reduce plaintext coordinates but recover little or no encrypted network bandwidth.",
    "Robust plaintext aggregators require individual update distances that a sum-only encrypted path intentionally hides.",
    "Prior evaluations seldom combine paired multi-seed utility, membership inference, gradient reconstruction, one-round poisoning, longitudinal poisoning, and service timing.",
  ], { left: 95, top: 145, width: 1090, height: 350 }, { fontSize: 26, spaceAfterPoints: 10 });
  const gap = slide.shapes.add({ geometry: "roundRect", name: "gap-response", position: { left: 115, top: 515, width: 1050, height: 100 }, fill: LIGHT_GREEN, line: { style: "solid", fill: GREEN, width: 2 } });
  gap.text = "Thesis response\nCAABC-FL aligns adaptive compression with CKKS blocks and places verification, validation, rollback, threshold policy, and witnessed audit evidence around the encrypted training round.";
  gap.text.style = { typeface: FONT, fontSize: 22, bold: true, color: BLUE, alignment: "center", verticalAlignment: "middle", autoFit: "shrinkText" };
  addNote(slide, "This gap defines our contribution boundary. We do not claim to solve every privacy or Byzantine problem. We implement and test a specific integrated design that converts compression into serialized ciphertext savings and adds release-time controls compatible with encrypted sums.");
}

// Slide 13: Methodology divider
addNote(presentation.slides.getItem(12), "The methodology section explains the end-to-end system, the experimental design, the dataset, and the registered analysis methods.");

// Slide 14: System approach
{
  const slide = presentation.slides.getItem(13);
  await addImage(slide, "system-architecture", path.join(workspaceDir, "output/png/secure_healthcare_fl_layered_architecture.png"), { left: 75, top: 120, width: 1130, height: 470 }, "Layered CAABC-FL architecture from hospital data preparation to governed global model release");
  addText(slide, "architecture-caption", "Fig. 1. End-to-end CAABC-FL architecture with privacy, encrypted transport, verification, governance, and audit layers.", { left: 115, top: 590, width: 1050, height: 40 }, { fontSize: 19, italic: true, alignment: "center" });
  addNote(slide, "The architecture separates local data handling, privacy and cryptography, local training, trust management, encrypted aggregation, model distribution, and inference. Hospitals keep patient records. The coordinator aggregates ciphertexts, while verification and release controls prevent an unchecked model update from becoming global.");
}

// Slide 15: Research design
{
  const slide = presentation.slides.getItem(14);
  const nodes = [
    ["PhysioNet 2019\n40,336 patients", GREEN],
    ["Natural split\nHospital A and B", BLUE],
    ["Five paired seeds\nFrozen protocol", GREEN],
    ["Baselines and\nCAABC-FL", BLUE],
    ["Utility, attacks,\nwire and systems", GREEN],
    ["Paired inference\nand claim boundary", BLUE],
  ];
  nodes.forEach(([text, color], index) => {
    const left = 65 + index * 200;
    const box = slide.shapes.add({ geometry: "roundRect", name: `design-step-${index + 1}`, position: { left, top: 245, width: 165, height: 120 }, fill: index % 2 === 0 ? LIGHT_GREEN : LIGHT_BLUE, line: { style: "solid", fill: color, width: 2 } });
    box.text = text;
    box.text.style = { typeface: FONT, fontSize: 22, bold: true, color: BLUE, alignment: "center", verticalAlignment: "middle", autoFit: "shrinkText" };
    if (index < nodes.length - 1) addRule(slide, left + 165, 302, 35, color, 4);
  });
  addBullets(slide, "design-bullets", [
    "Cross-silo client-server experiment with a naturally partitioned healthcare cohort.",
    "Same model, privacy budget, CKKS context, round budget, and evaluation split across compared methods.",
    "Claims restricted to the evaluated data, attacks, deployment, and trust assumptions.",
  ], { left: 150, top: 415, width: 980, height: 185 }, { fontSize: 24, spaceAfterPoints: 7 });
  addNote(slide, "The study uses a paired confirmatory design. Each method receives the same cohort, split, model, privacy configuration, training budget, and random seed. This controls many nuisance differences and supports paired confidence intervals and tests.");
}

// Slide 16: Data collection
{
  const slide = presentation.slides.getItem(15);
  addText(slide, "dataset-number", "40,336", { left: 90, top: 160, width: 350, height: 100 }, { fontSize: 62, bold: true, color: GREEN, alignment: "center" });
  addText(slide, "dataset-label", "patient records in the PhysioNet 2019 sepsis cohort", { left: 90, top: 260, width: 350, height: 105 }, { fontSize: 25, bold: true, color: BLUE, alignment: "center" });
  addRule(slide, 475, 150, 3, GREEN, 420);
  addBullets(slide, "collection-bullets", [
    "Open retrospective critical-care data released for the PhysioNet/Computing in Cardiology Challenge [19].",
    "Two natural source partitions retained as Hospital A and Hospital B rather than randomly mixing institutions.",
    "Patient records remain local during the simulated cross-silo training process.",
    "Consent and governance assumptions follow the public dataset terms. The study does not involve prospective patient recruitment.",
  ], { left: 530, top: 155, width: 650, height: 405 }, { fontSize: 25, spaceAfterPoints: 10 });
  addText(slide, "collection-source", "Source: Reyna et al., Critical Care Medicine, 2020 [19].", { left: 530, top: 575, width: 650, height: 35 }, { fontSize: 18, italic: true, color: MUTED });
  addNote(slide, "The study uses 40,336 patient records from the public PhysioNet 2019 sepsis challenge. We preserve the two source hospital partitions because cross-institutional heterogeneity is part of the research question. Source: Reyna et al. [19].");
}

// Slide 17: Data analysis
{
  const slide = presentation.slides.getItem(16);
  const headings = ["Utility", "Privacy", "Poisoning", "Systems and statistics"];
  const bodies = [
    "Accuracy, precision, recall, F1, AUROC, AUPRC, balanced accuracy, MCC, and Brier score.",
    "LiRA and RMIA membership inference with eight reference models per seed. A 300-step gradient reconstruction attack.",
    "Seven one-round attacks at 40% malicious clients and two longitudinal attack settings.",
    "Serialized CKKS bytes, latency, cryptographic correctness, five paired seeds, 95% t intervals, and Holm correction.",
  ];
  headings.forEach((heading, index) => {
    const row = Math.floor(index / 2);
    const col = index % 2;
    const left = 95 + col * 575;
    const top = 150 + row * 225;
    addText(slide, `analysis-heading-${index}`, heading, { left, top, width: 500, height: 50 }, { fontSize: 28, bold: true, color: col === 0 ? GREEN : BLUE });
    addRule(slide, left, top + 55, 500, col === 0 ? GREEN : CYAN, 3);
    addText(slide, `analysis-body-${index}`, bodies[index], { left, top: top + 75, width: 500, height: 125 }, { fontSize: 23 });
  });
  addNote(slide, "The analysis covers more than predictive accuracy. We measure ranking and threshold metrics, probability error, privacy attacks, poisoning effects, encrypted network bytes, cryptographic error, and service latency. Five paired seeds form the confirmatory unit, and Holm correction controls multiplicity within registered endpoint families.");
}

// Slide 18: Budget
{
  const slide = presentation.slides.getItem(17);
  addText(slide, "budget-summary", "No major project cost was required", { left: 160, top: 125, width: 960, height: 55 }, { fontSize: 31, bold: true, color: GREEN, alignment: "center" });
  addText(slide, "table-caption-budget", "TABLE IV. Resources used for the thesis", { left: 180, top: 190, width: 920, height: 35 }, { fontSize: 18, italic: true, alignment: "center" });
  const values = [
    ["Resource", "Provision", "Direct project cost"],
    ["PhysioNet 2019 dataset", "Public research dataset", "No fee"],
    ["Python, PyTorch, TenSEAL, OpenFHE", "Open-source software", "No licence fee"],
    ["Development hardware", "Existing personal computer", "No new purchase"],
    ["Documentation and collaboration", "University and existing services", "No major additional cost"],
  ];
  const table = slide.tables.add({ rows: values.length, columns: 3, left: 160, top: 235, width: 960, height: 330, columnWidths: [310, 390, 260], values });
  styleTable(table, values.length, 3, { fontSize: 18, headerFontSize: 19 });
  addText(slide, "budget-note", "Optional cloud hardware and production deployment were outside the funded scope.", { left: 170, top: 585, width: 940, height: 40 }, { fontSize: 21, italic: true, color: MUTED, alignment: "center" });
  addNote(slide, "The research used an open dataset, open-source tools, and existing hardware. We therefore report no major direct cost. Production-grade cloud infrastructure, hardware confidential computing, and clinical deployment remain future work rather than hidden project expenses.");
}

// Slide 19: Results divider
addNote(presentation.slides.getItem(18), "The results section presents the main utility and communication outcome, the same-protocol comparison, and the privacy, poisoning, and systems evidence.");

// Slide 20: Key findings
{
  const slide = presentation.slides.getItem(19);
  const metrics = [
    ["0.730", "Mean test AUROC", GREEN],
    ["0.384", "Mean test AUPRC", BLUE],
    ["56.0%", "Encrypted upload reduction", GREEN],
    ["0.496-0.507", "Private-model attack AUC", BLUE],
  ];
  metrics.forEach(([value, label, color], index) => {
    const left = 60 + index * 305;
    addText(slide, `metric-value-${index}`, value, { left, top: 175, width: 250, height: 90 }, { fontSize: index === 3 ? 43 : 56, bold: true, color, alignment: "center" });
    addText(slide, `metric-label-${index}`, label, { left, top: 270, width: 250, height: 85 }, { fontSize: 23, bold: true, color: BLUE, alignment: "center" });
    if (index < metrics.length - 1) addRule(slide, left + 275, 165, 2, BORDER, 205);
  });
  addBullets(slide, "finding-bullets", [
    "CAABC-FL passed the registered AUROC non-inferiority gate against dense DP-FedAvg-CKKS.",
    "The AUPRC difference was negative, so the evidence does not support universal utility superiority.",
    "The governance layer contained the tested longitudinal backdoor with 60% rollback and a 0.0293 clean-AUROC cost.",
    "OpenFHE 3-of-3 CKKS achieved maximum error of 1.34 x 10^-13, while the main service remained centrally keyed.",
  ], { left: 130, top: 395, width: 1020, height: 225 }, { fontSize: 23, spaceAfterPoints: 7 });
  addNote(slide, "The strongest result is the encrypted communication saving. CAABC-FL reduced serialized upload by about 56 percent while maintaining AUROC within the registered non-inferiority margin. AUPRC and several operating-point metrics declined, so we present a bounded trade-off rather than universal superiority.");
}

// Slide 21: Same-protocol comparison
{
  const slide = presentation.slides.getItem(20);
  addText(slide, "table-caption-comparison", "TABLE V. Five-seed same-protocol comparison", { left: 65, top: 120, width: 610, height: 35 }, { fontSize: 18, italic: true, alignment: "center" });
  const values = [
    ["Method", "AUROC", "AUPRC", "Upload (MiB)"],
    ["DP-FedAvg-CKKS", "0.731", "0.394", "63.20"],
    ["CAABC-FL", "0.730", "0.384", "27.81"],
    ["Fed-EF-SGD", "0.731", "0.395", "63.20"],
    ["Fed-EF-AMS", "0.732", "0.341", "63.20"],
    ["SoteriaFL-SGD", "0.727", "0.392", "63.21"],
  ];
  const table = slide.tables.add({ rows: values.length, columns: 4, left: 45, top: 165, width: 650, height: 385, columnWidths: [250, 130, 130, 140], values });
  styleTable(table, values.length, 4, { fontSize: 16.5, headerFontSize: 17 });
  const chart = slide.charts.add("bar", {
    position: { left: 725, top: 155, width: 500, height: 400 },
    title: "Actual encrypted upload reduction (%)",
    titleTextStyle: { typeface: FONT, fontSize: 18, bold: true, fill: BLUE },
    categories: ["DP-FedAvg", "CAABC-FL", "Fed-EF-SGD", "Fed-EF-AMS", "SoteriaFL"],
    series: [{ name: "Reduction", values: [0, 55.999, 0.0067, 0.0033, 0.0004], fill: GREEN, valuesFormatCode: "0.0" }],
    hasLegend: false,
    barOptions: { direction: "bar", grouping: "clustered", gapWidth: 45 },
    xAxis: { min: 0, max: 60, numberFormatCode: "0.0", majorGridlines: { style: "solid", fill: "#E2E8F0", width: 1 }, textStyle: { typeface: FONT, fontSize: 13 } },
    yAxis: { textStyle: { typeface: FONT, fontSize: 13 } },
    dataLabels: { showValue: true, position: "outEnd", textStyle: { typeface: FONT, fontSize: 13, bold: true, fill: TEXT } },
    chartFill: "#FFFFFF",
    chartLine: { style: "solid", fill: BORDER, width: 1 },
  });
  applyPresentationChartFont(chart, { fontFamily: FONT });
  addText(slide, "comparison-note", "Only CAABC-FL converted compression into a material serialized CKKS upload saving.", { left: 110, top: 575, width: 1060, height: 45 }, { fontSize: 22, bold: true, color: GREEN, alignment: "center" });
  addNote(slide, "All five methods use the same data, model, privacy, and CKKS conditions. Their AUROC values overlap. CAABC-FL alone reduces the serialized encrypted payload materially. Logical sparsity in the other compressed baselines disappears after dense CKKS encoding. Source: results/q1-sota-reproduction-v1/analysis/sota_method_summary.csv.");
}

// Slide 22: Security and systems performance
{
  const slide = presentation.slides.getItem(21);
  await addImage(slide, "privacy-results", path.join(workspaceDir, "results/q1-extension-v1/analysis/extension_advanced_privacy.png"), { left: 45, top: 130, width: 575, height: 380 }, "LiRA and RMIA membership-inference results across five paired seeds");
  await addImage(slide, "poisoning-results", path.join(workspaceDir, "results/q1-security-confirmatory-v1/analysis/confirmatory_poisoning_heatmap.png"), { left: 650, top: 130, width: 585, height: 380 }, "One-round poisoning AUROC changes for seven attacks and six aggregation defences");
  addText(slide, "privacy-caption", "Fig. 2. Membership-inference diagnostics. Values near 0.5 indicate chance-level discrimination.", { left: 60, top: 510, width: 545, height: 55 }, { fontSize: 17.5, italic: true, alignment: "center" });
  addText(slide, "poison-caption", "Fig. 3. Mean paired AUROC change at 40% malicious clients. More negative values indicate greater damage.", { left: 665, top: 510, width: 555, height: 55 }, { fontSize: 17.5, italic: true, alignment: "center" });
  addText(slide, "systems-summary", "System evidence: 16-client CKKS upload 25.28 MiB, end-to-end latency 7.080 s, and verified 3-of-3 OpenFHE correctness. These tests do not establish WAN or dropout-tolerant production performance.", { left: 115, top: 580, width: 1050, height: 55 }, { fontSize: 20.5, bold: true, color: BLUE, alignment: "center" });
  addNote(slide, "Membership-inference AUC remains near chance for the two private methods, but empirical attacks do not prove privacy. Mean aggregation fails under model replacement and sign flip. FLTrust and Multi-Krum perform well in plaintext but conflict with the implemented sum-only CKKS path. The service timing is single-host and sequential.");
}

// Slide 23: Conclusion divider
addNote(presentation.slides.getItem(22), "The final section summarizes what the study established, identifies the contributions and limitations, and outlines the next engineering steps.");

// Slide 24: Summary
{
  const slide = presentation.slides.getItem(23);
  const summaries = [
    ["Objective 1", "Achieved", "Implemented the layered privacy, encrypted aggregation, verification, release, and audit workflow."],
    ["Objective 2", "Achieved", "CAABC-FL reduced measured encrypted upload by 55.998% with an AUROC non-inferiority result."],
    ["Objective 3", "Achieved within scope", "Completed same-protocol utility, privacy, poisoning, cryptographic, and system evaluations."],
  ];
  summaries.forEach(([objective, status, evidence], index) => {
    const top = 155 + index * 150;
    addText(slide, `summary-objective-${index}`, objective, { left: 100, top, width: 190, height: 65 }, { fontSize: 26, bold: true, color: BLUE, verticalAlignment: "middle" });
    addText(slide, `summary-status-${index}`, status, { left: 315, top, width: 220, height: 65 }, { fontSize: 25, bold: true, color: GREEN, alignment: "center", verticalAlignment: "middle" });
    addText(slide, `summary-evidence-${index}`, evidence, { left: 565, top: top - 5, width: 610, height: 80 }, { fontSize: 23, verticalAlignment: "middle" });
    addRule(slide, 100, top + 92, 1075, BORDER, 1);
  });
  addText(slide, "summary-boundary", "Conclusion: CAABC-FL provides a defensible privacy-utility-communication trade-off under the registered protocol. The evidence does not support universal superiority or a production-decentralization claim.", { left: 125, top: 565, width: 1030, height: 65 }, { fontSize: 22.5, bold: true, color: BLUE, alignment: "center" });
  addNote(slide, "All three objectives were achieved within the stated scope. The implementation and evaluation support a bounded systems claim. We deliberately avoid claiming universal predictive superiority, formal Byzantine robustness, or a fully decentralized production deployment.");
}

// Slide 25: Contributions
{
  const slide = presentation.slides.getItem(24);
  const contributions = [
    ["Integrated framework", "A working cross-silo pipeline combines patient-level DP, CKKS aggregation, authenticated messages, verification, governed release, and witnessed audit evidence."],
    ["CAABC-FL", "Adaptive common blocks align with ciphertext packing, so compression reduces serialized network bytes while error feedback limits discarded-update loss."],
    ["Reproducible evaluation", "Five paired seeds cover utility, LiRA/RMIA, 300-step reconstruction, seven one-round attacks, longitudinal poisoning, CKKS correctness, and service timing."],
    ["Explicit claim boundary", "Negative AUPRC, rollback cost, central key custody, and deployment limits remain visible rather than being hidden by a single headline metric."],
  ];
  contributions.forEach(([heading, body], index) => {
    const row = Math.floor(index / 2);
    const col = index % 2;
    const left = 85 + col * 575;
    const top = 145 + row * 235;
    addText(slide, `contribution-heading-${index}`, heading, { left, top, width: 510, height: 55 }, { fontSize: 28, bold: true, color: col === 0 ? GREEN : BLUE });
    addRule(slide, left, top + 60, 500, col === 0 ? GREEN : CYAN, 3);
    addText(slide, `contribution-body-${index}`, body, { left, top: top + 80, width: 510, height: 135 }, { fontSize: 22.5 });
  });
  addNote(slide, "The main contribution is not a single security primitive. It is the integration and evidence: ciphertext-aligned compression, a complete governed training path, and a broad paired evaluation that records both positive and negative results.");
}

// Slide 26: Limitations
{
  const slide = presentation.slides.getItem(25);
  addBullets(slide, "limitations-bullets", [
    "One retrospective sepsis cohort, two source hospitals, one MLP, and no prospective or external clinical validation.",
    "The main TenSEAL service uses central key custody. The OpenFHE threshold experiment remains an isolated 3-of-3 test without dropout tolerance.",
    "Network timing comes from sequential single-host runs, not a wide-area multi-institution deployment.",
    "No physical Intel TDX or AMD SEV-SNP experiment, medical-device assessment, or stakeholder usability study.",
    "Membership, reconstruction, and poisoning findings remain specific to the registered attacks and five security seeds.",
  ], { left: 110, top: 145, width: 1060, height: 425 }, { fontSize: 25, spaceAfterPoints: 10 });
  addText(slide, "limitations-close", "These limitations restrict deployment claims but do not invalidate the measured protocol-level results.", { left: 145, top: 585, width: 990, height: 45 }, { fontSize: 22.5, bold: true, color: RED, alignment: "center" });
  addNote(slide, "We separate research-system evidence from production claims. The results remain valid for the registered experiment, but they do not prove clinical effectiveness across hospitals or remove the need for networked key custodians, confidential hardware, and external evaluation.");
}

// Slide 27: Future work
{
  const slide = presentation.slides.getItem(26);
  const items = [
    ["Threshold custody", "Integrate dropout-tolerant t-of-n decryption with networked independent custodians."],
    ["Encrypted robustness", "Develop secure robust statistics that do not require exposing individual plaintext updates."],
    ["Production deployment", "Run concurrent multi-host WAN experiments and physical TDX or SEV-SNP attestation."],
    ["Clinical generalization", "Evaluate additional institutions, diseases, model families, fairness endpoints, and prospective workflows."],
    ["Independent assurance", "Audit secure randomness, cryptographic configuration, governance logic, and threat-control evidence."],
  ];
  items.forEach(([heading, body], index) => {
    const top = 130 + index * 98;
    addText(slide, `future-heading-${index}`, heading, { left: 100, top, width: 270, height: 55 }, { fontSize: 25, bold: true, color: index % 2 === 0 ? GREEN : BLUE, verticalAlignment: "middle" });
    addText(slide, `future-body-${index}`, body, { left: 390, top, width: 790, height: 60 }, { fontSize: 23, verticalAlignment: "middle" });
    if (index < items.length - 1) addRule(slide, 100, top + 72, 1080, BORDER, 1);
  });
  addNote(slide, "The next phase should strengthen decentralization and external validity. The highest priority is service-integrated threshold custody, followed by privacy-compatible robust aggregation and real multi-host confidential deployment.");
}

// Slides 28 and 29: References
const referencesA = [
  "[1] H. B. McMahan et al., 'Communication-Efficient Learning of Deep Networks from Decentralized Data,' AISTATS, 2017.",
  "[2] M. J. Sheller et al., 'Federated Learning in Medicine,' Scientific Reports, vol. 10, 2020.",
  "[3] I. Dayan et al., 'Federated Learning for Predicting Clinical Outcomes in Patients with COVID-19,' Nature Medicine, 2021.",
  "[4] R. Shokri et al., 'Membership Inference Attacks Against Machine Learning Models,' IEEE S&P, 2017.",
  "[5] L. Zhu, Z. Liu, and S. Han, 'Deep Leakage from Gradients,' NeurIPS, 2019.",
  "[6] J. Geiping et al., 'Inverting Gradients - How Easy Is It to Break Privacy in Federated Learning?' NeurIPS, 2020.",
  "[7] C. Dwork et al., 'Calibrating Noise to Sensitivity in Private Data Analysis,' TCC, 2006.",
  "[8] M. Abadi et al., 'Deep Learning with Differential Privacy,' ACM CCS, 2016.",
];
const referencesB = [
  "[9] K. Bonawitz et al., 'Practical Secure Aggregation for Privacy-Preserving Machine Learning,' ACM CCS, 2017.",
  "[10] J. H. Cheon et al., 'Homomorphic Encryption for Arithmetic of Approximate Numbers,' ASIACRYPT, 2017.",
  "[11] T. Stevens et al., 'Efficient Differentially Private Secure Aggregation for Federated Learning,' USENIX Security, 2022.",
  "[12] D. Froelicher et al., 'Truly Privacy-Preserving Federated Analytics for Precision Medicine,' Nature Communications, 2021.",
  "[13] Z. Li et al., 'SoteriaFL,' NeurIPS, 2022.   [14] X. Li and P. Li, 'Analysis and Enhancement of Federated Learning with Biased Compression,' ICML, 2023.",
  "[15] X. Cao et al., 'FLTrust,' NDSS, 2021.   [16] R. Xu et al., 'Dual Defense,' NeurIPS, 2024.",
  "[17] X. Gu, M. Li, and L. Xiong, 'DP-BREM,' USENIX Security, 2025.   [18] H. Asi et al., 'PREAMBLE,' NeurIPS, 2025.",
  "[19] M. A. Reyna et al., 'Early Prediction of Sepsis from Clinical Data,' Critical Care Medicine, 2020.",
];

for (const [slideNumber, refs, start] of [[28, referencesA, 0], [29, referencesB, 0]]) {
  const slide = presentation.slides.getItem(slideNumber - 1);
  refs.forEach((reference, index) => {
    addText(slide, `reference-${slideNumber}-${index}`, reference, { left: 85, top: 120 + index * 63, width: 1110, height: 55 }, { fontSize: 18.5, color: TEXT });
  });
  addNote(slide, slideNumber === 28 ? "These references cover the foundations of federated learning, healthcare collaboration, differential privacy, membership inference, and gradient reconstruction." : "These references cover secure aggregation, CKKS, privacy-aware communication, poisoning defence, recent integrated methods, and the PhysioNet sepsis dataset.");
}

// Slide 30: Q&A
{
  const slide = presentation.slides.getItem(29);
  const central = bySlide(30, ["textbox"]).find((record) => String(record.text).includes("Any Questions"));
  if (central) presentation.resolve(central.id).text = "Questions and Discussion";
  addNote(slide, "Thank you for listening. We welcome questions about the architecture, CAABC-FL, the evaluation protocol, the claim boundaries, and the next deployment steps.");
}

// Slide 31: Thank you
{
  const slide = presentation.slides.getItem(30);
  const thank = bySlide(31, ["textbox"]).find((record) => String(record.text).includes("Thank You"));
  const tagline = bySlide(31, ["textbox"]).find((record) => String(record.text).includes("Keep Learning"));
  if (thank) {
    const target = presentation.resolve(thank.id);
    target.text = "Thank You";
    target.text.style = { typeface: FONT, fontSize: 48, bold: true, color: BLUE, alignment: "center", autoFit: "shrinkText" };
  }
  if (tagline) {
    const target = presentation.resolve(tagline.id);
    target.text = "CAABC-FL: Secure collaboration with explicit trust boundaries";
    target.text.style = { typeface: FONT, fontSize: 24, bold: true, color: TEXT, alignment: "center", autoFit: "shrinkText" };
  }
  addNote(slide, "This final slide remains on screen after the question session.");
}

// Refresh all page numbers and footer text after edits.
const finalSnapshot = await presentation.inspect({ kind: "textbox", include: "id,slide,text,bbox", maxChars: 100000 });
for (const line of finalSnapshot.ndjson.split("\n").filter(Boolean)) {
  const record = JSON.parse(line);
  const [left, top] = record.bbox ?? [0, 0, 0, 0];
  const target = presentation.resolve(record.id);
  if (record.slide > 1 && top > 675 && left > 230 && left < 1050) target.text = shortFooter;
  if (top > 640 && left < 240) target.text = "Fall 2025";
  if (top > 620 && left > 1100) target.text = String(record.slide);
}

const candidatePath = path.join(stagingDir, "CAABC-FL_Final_Defense_Fall_2025_Ready_candidate.pptx");
await (await PresentationFile.exportPptx(presentation)).save(candidatePath);

const requirements = {
  explicitTotalSlideCount: 31,
  sourceTemplatePath: sourcePath,
  requiredNativeTableOwnerSlides: [9, 10, 11, 18, 21],
  requiredNativeChartOwnerSlides: [21],
  materializeLiteralChartWorkbooks: true,
  nativeChartTargetApplication: "powerpoint",
};
const fontPolicy = {
  basis: "reference",
  families: ["Arial", "Corbel"],
  referencePath: sourcePath,
  referenceSha256: "d0b901bbb74d3fbfd69a16bfccf4d0e56ccbc6d560c8f30ce099b3ef93f6e4ce",
};

const result = await finalizePresentation({
  ...requirements,
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
    ...[9, 10, 11, 18, 21].flatMap((number) => ["--require-native-table-slide", String(number)]),
  ],
  requiredNativeTableOwnerSlides: requirements.requiredNativeTableOwnerSlides,
  requiredNativeChartOwnerSlides: requirements.requiredNativeChartOwnerSlides,
  materializeLiteralChartWorkbooks: true,
  nativeChartTargetApplication: "powerpoint",
  fontPolicy,
  verifyArtifactToolImport: true,
  receiptPath: path.join(stagingDir, "CAABC-FL_Final_Defense_Fall_2025_Ready.validation.json"),
});

console.log(JSON.stringify({ finalPath, slideCount: presentation.slides.items.length, result }, null, 2));
