import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const sourcePath = "E:/PrivacyPreserving-Healthcare-FL/.codex-finalizer/CAABC-FL_Final_Defense_25_September_2026_Complete_candidate.pptx";
const presentation = await PresentationFile.importPptx(await FileBlob.load(sourcePath));
const snapshot = await presentation.inspect({
  kind: "slide,table,chart",
  include: "id,slide,title,rows,cols,chartType,preview",
  maxChars: 50000,
});
console.log(snapshot.ndjson);
