import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const sourcePath = "E:/PrivacyPreserving-Healthcare-FL/output/presentation/CAABC-FL_Final_Defense_25_September_2026_Title_Background.pptx";
const presentation = await PresentationFile.importPptx(await FileBlob.load(sourcePath));
const snapshot = await presentation.inspect({
  kind: "slide,textbox,shape,image,table,chart,layout",
  include: "id,slide,name,title,textPreview,text,bbox,rows,cols,chartType,placeholders",
  maxChars: 180000,
});
for (const line of snapshot.ndjson.split("\n").filter(Boolean)) {
  const record = JSON.parse(line);
  if (record.kind === "slide" || record.slide === 2 || record.slide === 18 || record.slide === 7 || record.slide === 17) console.log(line);
}
