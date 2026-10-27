import fs from "node:fs/promises";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const sourcePath = "E:/PrivacyPreserving-Healthcare-FL/output/presentation/Board-11_Group-2_CAABC-FL_Final_Defense_Contributions_v3.pptx";
const outDir = "E:/PrivacyPreserving-Healthcare-FL/tmp/ppt_build/limitations_before";
await fs.mkdir(outDir, { recursive: true });

const presentation = await PresentationFile.importPptx(await FileBlob.load(sourcePath));
const slide = presentation.slides.items[33];
const detail = await presentation.inspect({
  target: { id: slide.id, beforeLines: 0, afterLines: 200 },
  kind: "slide,textbox,shape,image,table,chart,notes,layout",
  maxChars: 30000,
});
console.log(detail.ndjson);

const png = await slide.export({ format: "png", scale: 2 });
await fs.writeFile(`${outDir}/slide-34-before.png`, new Uint8Array(await png.arrayBuffer()));
const layout = await slide.export({ format: "layout" });
await fs.writeFile(`${outDir}/slide-34-before.layout.json`, await layout.text());
