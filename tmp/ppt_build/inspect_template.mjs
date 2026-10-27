import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const sourcePath = "E:/Download/Final Defence Thesis-Project Presentation Slide For Spring 2025.pptx";

const presentation = await PresentationFile.importPptx(await FileBlob.load(sourcePath));
const snapshot = await presentation.inspect({
  kind: "deck,slide,textbox,shape,image,table,chart,notes,layout",
  include: "id,slide,name,title,text,textPreview,textChars,textLines,bbox,bboxUnit,rows,cols,chartType,alt,isPlaceholder,placeholders",
  maxChars: 120000,
});

const metadata = {
  slideCount: presentation.slides.items.length,
  masterCount: presentation.masters.items.length,
  layoutCount: presentation.layouts.items.length,
  masters: presentation.masters.items.map((master) => ({ id: master.id, name: master.name })),
  layouts: presentation.layouts.items.map((layout) => ({
    id: layout.id,
    name: layout.name,
    placeholders: layout.placeholders.summary(),
  })),
};

console.log(JSON.stringify(metadata, null, 2));
console.log(snapshot.ndjson);
