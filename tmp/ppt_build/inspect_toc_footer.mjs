import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const sourcePath = "E:/PrivacyPreserving-Healthcare-FL/output/presentation/CAABC-FL_Final_Defense_25_September_2026_Organized_TOC.pptx";
const presentation = await PresentationFile.importPptx(await FileBlob.load(sourcePath));
const slide = presentation.slides.getItem(1);
const result = await slide.export({ format: "layout" });
console.log(await result.text());
