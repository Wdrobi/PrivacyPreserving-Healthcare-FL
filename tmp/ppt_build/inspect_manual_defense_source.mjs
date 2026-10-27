import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const sourcePath = "C:/Users/HP/Downloads/Board-11_Group-2_CAABC-FL_Final_Defense.pptx";
const presentation = await PresentationFile.importPptx(await FileBlob.load(sourcePath));
const snapshot = await presentation.inspect({ kind: "slide,table,chart", maxChars: 100000 });
console.log(snapshot.ndjson);
