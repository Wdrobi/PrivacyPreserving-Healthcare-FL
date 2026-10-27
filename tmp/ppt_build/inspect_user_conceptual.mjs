import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const sourcePath = "C:/Users/HP/Downloads/Board-11_Group-2_CAABC-FL_Final_Defense.pptx";
const outDir = "E:/PrivacyPreserving-Healthcare-FL/tmp/ppt_build/user_conceptual_before";
await fs.mkdir(outDir, { recursive: true });
const presentation = await PresentationFile.importPptx(await FileBlob.load(sourcePath));
const hits = await presentation.inspect({
  kind: "slide,textbox,shape,image,notes,layout",
  search: "Conceptual Framework",
  maxChars: 12000,
});
console.log(hits.ndjson);
const records = hits.ndjson.split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line));
const slideRecord = records.find((record) => record.kind === "slide" && record.title === "Conceptual Framework");
if (!slideRecord) throw new Error("Conceptual Framework slide not found.");
const slide = presentation.resolve(slideRecord.id);
const focused = await presentation.inspect({
  target: { id: slideRecord.id, beforeLines: 0, afterLines: 100 },
  kind: "slide,textbox,shape,image,notes,layout",
  maxChars: 30000,
});
await fs.writeFile(path.join(outDir, "inspect.txt"), focused.ndjson);
console.log(focused.ndjson);
const preview = await slide.export({ format: "png", scale: 2 });
await fs.writeFile(path.join(outDir, `slide-${slideRecord.slide}.png`), new Uint8Array(await preview.arrayBuffer()));
const layout = await slide.export({ format: "layout" });
await fs.writeFile(path.join(outDir, `slide-${slideRecord.slide}.layout.json`), await layout.text());
const deck = await presentation.inspect({ kind: "deck,slide,table,chart", maxChars: 30000 });
await fs.writeFile(path.join(outDir, "deck.txt"), deck.ndjson);
console.log(`CONCEPTUAL_SLIDE=${slideRecord.slide}`);
console.log(`SLIDE_COUNT=${presentation.slides.items.length}`);
