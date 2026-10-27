import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const sourcePath = "E:/PrivacyPreserving-Healthcare-FL/output/presentation/Board-11_Group-2_CAABC-FL_Final_Defense_With_CAABC_Algorithm_v3.pptx";
const outDir = "E:/PrivacyPreserving-Healthcare-FL/tmp/ppt_build/key_findings_before";
await fs.mkdir(outDir, { recursive: true });
const presentation = await PresentationFile.importPptx(await FileBlob.load(sourcePath));
const snapshot = await presentation.inspect({
  kind: "slide,textbox,shape,notes,layout",
  target: { id: "sl/3mdove10", beforeLines: 0, afterLines: 30 },
  include: "id,slide,name,title,text,textPreview,bbox,bboxUnit",
  maxChars: 16000,
});
await fs.writeFile(path.join(outDir, "inspect.txt"), snapshot.ndjson);
const slide = presentation.slides.getItem(27);
const preview = await slide.export({ format: "png", scale: 2 });
await fs.writeFile(path.join(outDir, "slide-28.png"), new Uint8Array(await preview.arrayBuffer()));
const layout = await slide.export({ format: "layout" });
await fs.writeFile(path.join(outDir, "slide-28.layout.json"), await layout.text());
console.log(snapshot.ndjson);
