import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const sourcePath = "E:/PrivacyPreserving-Healthcare-FL/output/presentation/CAABC-FL_Final_Defense_25_September_2026_Title_Background.pptx";
const presentation = await PresentationFile.importPptx(await FileBlob.load(sourcePath));
for (const query of [
  "shape.delete|slide.shapes.delete|remove shape",
  "slide.duplicate|slide.moveTo|slides.add|slide order",
  "slide.tables.add|table cell style|table column widths",
  "table.delete|image.delete|chart.delete|table formatting|cell fill",
]) {
  const result = presentation.help("*", { search: query, include: ["index", "examples", "notes"], maxChars: 16000 });
  console.log(`\n=== ${query} ===\n${result.ndjson}`);
}
const table = presentation.resolve("tb/oje5k3ul");
console.log("TABLE_METHODS", {
  delete: typeof table.delete,
  setPosition: typeof table.setPosition,
  cells: typeof table.cells,
  getCell: typeof table.getCell,
});
const budgetSlide = presentation.slides.getItem(17);
console.log("TABLE_COLLECTION", {
  getItem: typeof budgetSlide.tables.getItem,
  items: Array.isArray(budgetSlide.tables.items),
  count: budgetSlide.tables.items?.length,
});
const objectiveSlide = presentation.slides.getItem(6);
console.log("SHAPE_COLLECTION", {
  getItem: typeof objectiveSlide.shapes.getItem,
  items: Array.isArray(objectiveSlide.shapes.items),
  count: objectiveSlide.shapes.items?.length,
});
