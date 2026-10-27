import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const presentation = await PresentationFile.importPptx(await FileBlob.load("E:/PrivacyPreserving-Healthcare-FL/output/presentation/Board-11_Group-2_CAABC-FL_Final_Defense_With_Conceptual_Framework_v2.pptx"));
const result = await presentation.inspect({ kind: "textbox,shape", search: "Future Work", maxChars: 12000 });
console.log(result.ndjson);
