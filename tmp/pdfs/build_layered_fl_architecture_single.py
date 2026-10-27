import importlib.util
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(__file__).with_name("build_layered_fl_architecture_compatible.py")
OUT = ROOT / "output" / "pdf"
OUT.mkdir(parents=True, exist_ok=True)
PDF_PATH = OUT / "secure_healthcare_fl_architecture_single.pdf"

spec = importlib.util.spec_from_file_location("compatible_architecture", SOURCE)
arch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(arch)

W, H = 1000, 1480


def no_header(*_args, **_kwargs):
    return None


def build():
    c = canvas.Canvas(str(PDF_PATH), pagesize=(W, H), pageCompression=1)
    c.setTitle("Secure Healthcare FL Layered Architecture - Single Diagram")
    c.setAuthor("Privacy-Preserving Healthcare FL")
    c.setSubject("Single-page collision-free layered security architecture")
    c.setFillColor(arch.C["white"])
    c.rect(0, 0, W, H, fill=1, stroke=0)

    c.setFillColor(arch.C["ink"])
    c.setFont(arch.BOLD, 23)
    c.drawString(30, 1440, "Secure Healthcare FL Layered Architecture")
    c.setFillColor(arch.C["muted"])
    c.setFont(arch.FONT, 10.2)
    c.drawString(30, 1417, "Governance, privacy-safe training, secure aggregation, verified distribution and clinical inference")
    c.setStrokeColor(HexColor("#CDD5DF"))
    c.setLineWidth(0.7)
    c.line(30, 1399, W - 30, 1399)

    # Reuse the verified collision-free panel geometry without duplicate page headers.
    original_header = arch.page_header
    original_key = arch.continuation_key
    arch.page_header = no_header
    arch.continuation_key = no_header
    try:
        c.saveState()
        c.translate(0, 675)
        arch.draw_page_one(c)
        c.restoreState()

        arch.draw_page_two(c)
    finally:
        arch.page_header = original_header
        arch.continuation_key = original_key

    c.setFillColor(arch.C["muted"])
    c.setFont(arch.FONT, 7.5)
    c.drawCentredString(
        W / 2,
        685,
        "Dependency markers: A signed update -> TLS   B key shares -> threshold decryption   C consent registry -> inference check   D next round -> local training",
    )
    c.drawCentredString(W / 2, 15, "A-D markers replace long cross-layer rails so node cards and labels remain unobstructed.")

    c.showPage()
    c.save()
    print(PDF_PATH)


if __name__ == "__main__":
    build()
