import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const sourcePath = "E:/PrivacyPreserving-Healthcare-FL/output/presentation/Board-11_Group-2_CAABC-FL_Final_Defense_With_Algorithm_Gradient_Reconstruction_v4.pptx";
const presentation = await PresentationFile.importPptx(await FileBlob.load(sourcePath));
const slidesSnapshot = await presentation.inspect({ kind: "slide", maxChars: 30000 });
const slideRecords = slidesSnapshot.ndjson
  .split(/\r?\n/)
  .filter(Boolean)
  .map((line) => JSON.parse(line))
  .filter((record) => record.kind === "slide");

for (const record of slideRecords) {
  const focused = await presentation.inspect({
    target: { id: record.id, beforeLines: 0, afterLines: 100 },
    kind: "slide,textbox,notes",
    maxChars: 20000,
  });
  const records = focused.ndjson
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => JSON.parse(line));
  const slideRecord = records.find((item) => item.kind === "slide");
  const notesRecord = records.find((item) => item.kind === "notes");
  console.log(JSON.stringify({
    slide: record.slide,
    title: slideRecord?.title ?? "",
    notes: notesRecord?.text ?? "",
  }));
}
