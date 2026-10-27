from pathlib import Path

from pypdf import PdfReader


pdf_path = Path(r"E:\Download\caabc_fl_ieee_conference.pdf")
reader = PdfReader(str(pdf_path))

page_texts = []
for page_no, page in enumerate(reader.pages, 1):
    page_text = page.extract_text() or ""
    page_texts.append(page_text)
    preview = page_text[:120].replace("\n", " | ")
    print(
        f"PAGE {page_no}: chars={len(page_text)} "
        f"words={len(page_text.split())} first={preview}"
    )

full_text = "\n".join(page_texts)
for token in ("??", "TODO", "PLACEHOLDER", "undefined", "Error", "Warning"):
    print(f"TOKEN {token}: {full_text.lower().count(token.lower())}")

print(f"METADATA: {reader.metadata}")
print(f"FIRST LINE: {full_text.splitlines()[0] if full_text.splitlines() else ''}")

seen_fonts = set()
print("FONTS:")
for page in reader.pages:
    resources = page.get("/Resources") or {}
    fonts = resources.get("/Font") or {}
    for font_ref in fonts.values():
        font = font_ref.get_object()
        base = str(font.get("/BaseFont", ""))
        subtype = str(font.get("/Subtype", ""))
        descriptor = font.get("/FontDescriptor")
        embedded = False
        if descriptor:
            descriptor = descriptor.get_object()
            embedded = any(
                key in descriptor for key in ("/FontFile", "/FontFile2", "/FontFile3")
            )
        row = (base, subtype, embedded)
        if row not in seen_fonts:
            seen_fonts.add(row)
            print(row)
