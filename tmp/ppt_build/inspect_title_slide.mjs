import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const sourcePath = "E:/PrivacyPreserving-Healthcare-FL/output/presentation/CAABC-FL_Final_Defense_25_September_2026_Final_v2.pptx";
const presentation = await PresentationFile.importPptx(await FileBlob.load(sourcePath));
const snapshot = await presentation.inspect({
  kind: "slide,textbox,shape,image,layout",
  include: "id,slide,name,type,text,bbox,src,fill,line,zIndex",
  maxChars: 80000,
});
for (const line of snapshot.ndjson.split("\n").filter(Boolean)) {
  const record = JSON.parse(line);
  if (record.slide === 1 || record.type === "slide") console.log(line);
}
