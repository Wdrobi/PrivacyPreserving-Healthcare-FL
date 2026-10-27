from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output" / "pdf"
OUT.mkdir(parents=True, exist_ok=True)
PDF_PATH = OUT / "privacy_preserving_client_update_pipeline.pdf"
W, H = 1440, 900

C = {
    "ink": HexColor("#172536"),
    "muted": HexColor("#667085"),
    "line": HexColor("#8FA0B2"),
    "panel": HexColor("#F8FAFC"),
    "panel_stroke": HexColor("#E3E8EF"),
    "private_fill": HexColor("#F0EDFC"),
    "private_stroke": HexColor("#7764B4"),
    "private_badge": HexColor("#6653A2"),
    "public_fill": HexColor("#EAF1FB"),
    "public_stroke": HexColor("#5277A3"),
    "public_badge": HexColor("#315F91"),
    "crypto_fill": HexColor("#E7F6F3"),
    "crypto_stroke": HexColor("#4A8D85"),
    "crypto_badge": HexColor("#33766F"),
    "decision_fill": HexColor("#FFF3D8"),
    "decision_stroke": HexColor("#AD7B24"),
    "danger_fill": HexColor("#FDE8E7"),
    "danger_stroke": HexColor("#B75353"),
    "danger_badge": HexColor("#A84444"),
    "white": HexColor("#FFFFFF"),
}


def register_fonts():
    for name, path in [
        ("UI", r"C:\\Windows\\Fonts\\segoeui.ttf"),
        ("UIB", r"C:\\Windows\\Fonts\\seguisb.ttf"),
    ]:
        if Path(path).exists():
            try:
                pdfmetrics.registerFont(TTFont(name, path))
            except Exception:
                pass
    regular = "UI" if "UI" in pdfmetrics.getRegisteredFontNames() else "Helvetica"
    bold = "UIB" if "UIB" in pdfmetrics.getRegisteredFontNames() else "Helvetica-Bold"
    return regular, bold


FONT, BOLD = register_fonts()


def rounded(c, x, y, w, h, fill, stroke, radius=10, width=1.25):
    c.setFillColor(fill)
    c.setStrokeColor(stroke)
    c.setLineWidth(width)
    c.roundRect(x, y, w, h, radius, fill=1, stroke=1)


def centered_lines(c, lines, x, y, w, h, size=12.8, leading=15.5, bold=False, color=None):
    c.setFont(BOLD if bold else FONT, size)
    c.setFillColor(color or C["ink"])
    center_y = y + h / 2
    first_y = center_y + ((len(lines) - 1) * leading) / 2 - size * 0.34
    for i, line in enumerate(lines):
        c.drawCentredString(x + w / 2, first_y - i * leading, line)


def node(c, x, y, w, h, lines, kind="private", size=12.8, leading=15.5):
    rounded(c, x, y, w, h, C[f"{kind}_fill"], C[f"{kind}_stroke"])
    centered_lines(c, lines, x, y, w, h, size=size, leading=leading)


def arrow(c, points, color=None, dashed=False, label=None, label_xy=None):
    color = color or C["line"]
    c.setStrokeColor(color)
    c.setFillColor(color)
    c.setLineWidth(1.55)
    c.setLineJoin(1)
    c.setLineCap(1)
    c.setDash(5, 4) if dashed else c.setDash()
    p = c.beginPath()
    p.moveTo(*points[0])
    for px, py in points[1:]:
        p.lineTo(px, py)
    c.drawPath(p, fill=0, stroke=1)
    x2, y2 = points[-1]
    x1, y1 = points[-2]
    dx, dy = x2 - x1, y2 - y1
    length = max((dx * dx + dy * dy) ** 0.5, 0.001)
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    tip_back = 7.5
    half = 4.2
    q = c.beginPath()
    q.moveTo(x2, y2)
    q.lineTo(x2 - ux * tip_back + px * half, y2 - uy * tip_back + py * half)
    q.lineTo(x2 - ux * tip_back - px * half, y2 - uy * tip_back - py * half)
    q.close()
    c.drawPath(q, fill=1, stroke=0)
    c.setDash()
    if label and label_xy:
        lx, ly = label_xy
        c.setFillColor(C["white"])
        c.roundRect(lx - 5, ly - 4, pdfmetrics.stringWidth(label, BOLD, 9.5) + 10, 16, 6, fill=1, stroke=0)
        c.setFillColor(color)
        c.setFont(BOLD, 9.5)
        c.drawString(lx, ly, label)


def curve_arrow(c, start, controls, end, label=None, label_xy=None):
    color = C["line"]
    c.setStrokeColor(color)
    c.setFillColor(color)
    c.setLineWidth(1.55)
    p = c.beginPath()
    p.moveTo(*start)
    p.curveTo(*controls[0], *controls[1], *end)
    c.drawPath(p, fill=0, stroke=1)
    x2, y2 = end
    cx, cy = controls[1]
    dx, dy = x2 - cx, y2 - cy
    length = max((dx * dx + dy * dy) ** 0.5, 0.001)
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    q = c.beginPath()
    q.moveTo(x2, y2)
    q.lineTo(x2 - ux * 7.5 + px * 4.2, y2 - uy * 7.5 + py * 4.2)
    q.lineTo(x2 - ux * 7.5 - px * 4.2, y2 - uy * 7.5 - py * 4.2)
    q.close()
    c.drawPath(q, fill=1, stroke=0)
    if label and label_xy:
        c.setFillColor(C["white"])
        c.roundRect(label_xy[0] - 5, label_xy[1] - 4, 31, 16, 6, fill=1, stroke=0)
        c.setFillColor(color)
        c.setFont(BOLD, 9.5)
        c.drawString(label_xy[0], label_xy[1], label)


def phase(c, x, y, w, h, number, title, subtitle, badge_color):
    c.setFillColor(C["panel"])
    c.setStrokeColor(C["panel_stroke"])
    c.setLineWidth(1)
    c.roundRect(x, y, w, h, 16, fill=1, stroke=1)
    hy = y + h - 28
    c.setFillColor(badge_color)
    c.circle(x + 24, hy + 1, 14, fill=1, stroke=0)
    c.setFillColor(C["white"])
    c.setFont(BOLD, 9.5)
    c.drawCentredString(x + 24, hy - 2.2, number)
    c.setFillColor(C["ink"])
    c.setFont(BOLD, 15.2)
    c.drawString(x + 47, hy - 4.5, title)
    c.setFillColor(C["muted"])
    c.setFont(FONT, 9.2)
    c.drawRightString(x + w - 18, hy - 3, subtitle.upper())


def diamond(c, cx, cy, w, h):
    c.setFillColor(C["decision_fill"])
    c.setStrokeColor(C["decision_stroke"])
    c.setLineWidth(1.35)
    p = c.beginPath()
    p.moveTo(cx, cy + h / 2)
    p.lineTo(cx + w / 2, cy)
    p.lineTo(cx, cy - h / 2)
    p.lineTo(cx - w / 2, cy)
    p.close()
    c.drawPath(p, fill=1, stroke=1)
    centered_lines(c, ["Privacy budget", "available?"], cx - w / 2, cy - h / 2, w, h, size=11.6, leading=13.5, bold=True)


def build():
    c = canvas.Canvas(str(PDF_PATH), pagesize=(W, H), pageCompression=1)
    c.setTitle("Privacy-Preserving Client Update Pipeline")
    c.setAuthor("Privacy-Preserving Healthcare FL")
    c.setSubject("DP-safe adaptive compression and encrypted transport")
    c.setFillColor(C["white"])
    c.rect(0, 0, W, H, fill=1, stroke=0)

    c.setFillColor(C["ink"])
    c.setFont(BOLD, 25.5)
    c.drawString(50, 850, "Privacy-Preserving Client Update Pipeline")
    c.setFillColor(C["muted"])
    c.setFont(FONT, 12.4)
    c.drawString(50, 827, "DP-safe adaptive compression, privacy accounting and encrypted transport")
    c.setStrokeColor(HexColor("#CDD5DF"))
    c.setLineWidth(0.8)
    c.line(50, 808, W - 50, 808)

    phase(c, 50, 575, 1340, 210, "01", "Local training & privacy protection", "Private processing", C["private_badge"])
    phase(c, 50, 330, 1340, 210, "02", "DP-safe adaptive compression", "Private + public inputs", C["public_badge"])
    phase(c, 50, 80, 1340, 210, "03", "Secure packaging & transport", "Confidential transmission", C["crypto_badge"])

    # Phase 1: local update and privacy protection.
    node(c, 80, 615, 150, 56, ["Local model training"], size=13.2)
    node(c, 260, 615, 170, 56, ["Compute local", "gradient"], size=13.0)
    node(c, 500, 615, 210, 56, ["Add residual, then apply", "L2-norm clipping"], size=12.7)
    node(c, 500, 692, 210, 44, ["Previous compression residual"], size=11.9)
    node(c, 760, 615, 170, 56, ["Add calibrated", "Gaussian noise"], size=12.8)
    node(c, 970, 615, 220, 56, ["Update Rényi-DP accountant", "and enforce privacy budget"], size=12.2)
    diamond(c, 1305, 643, 146, 88)
    node(c, 1217, 548, 176, 46, ["Stop client participation", "or renegotiate privacy policy"], kind="danger", size=10.8, leading=12.5)

    arrow(c, [(230, 643), (260, 643)])
    arrow(c, [(430, 643), (500, 643)])
    arrow(c, [(605, 692), (605, 671)])
    arrow(c, [(710, 643), (760, 643)])
    arrow(c, [(930, 643), (970, 643)])
    arrow(c, [(1190, 643), (1232, 643)])
    arrow(c, [(1305, 599), (1305, 594)], color=C["danger_stroke"], label="No", label_xy=(1314, 597))

    # Phase 2: public budget inputs and DP-safe compression.
    node(c, 80, 424, 190, 54, ["Public network state", "bandwidth, latency, round budget"], kind="public", size=10.9, leading=13.0)
    node(c, 80, 350, 190, 54, ["Public compression policy", "target ratio and maximum K"], kind="public", size=11.0, leading=13.0)
    node(c, 300, 387, 190, 58, ["Select public", "payload budget K"], kind="public", size=12.5)
    node(c, 515, 414, 190, 58, ["Sanitized DP gradient"], size=12.8)
    node(c, 735, 414, 190, 58, ["Importance scoring on", "DP-sanitized gradient only"], size=12.0, leading=14.2)
    node(c, 970, 414, 190, 58, ["Select top-K sanitized", "coordinates"], size=12.5)
    node(c, 1190, 414, 170, 58, ["Stochastic", "quantization"], size=12.8)
    node(c, 970, 342, 190, 50, ["Compute local", "compression residual"], size=11.9, leading=13.5)

    arrow(c, [(270, 451), (285, 451), (285, 430), (300, 430)])
    arrow(c, [(270, 377), (285, 377), (285, 402), (300, 402)])
    arrow(c, [(845, 615), (845, 505), (610, 505), (610, 472)])
    arrow(c, [(705, 443), (735, 443)])
    arrow(c, [(925, 443), (970, 443)])
    arrow(c, [(490, 416), (490, 492), (1065, 492), (1065, 472)], label="K", label_xy=(1040, 497))
    arrow(c, [(1160, 443), (1190, 443)])
    arrow(c, [(1065, 414), (1065, 392)])
    curve_arrow(c, (1241, 617), ((1195, 558), (955, 535)), (830, 472), label="Yes", label_xy=(1090, 541))

    # Feedback residual loop, routed outside the content cards.
    arrow(
        c,
        [(1160, 367), (1375, 367), (1375, 715), (710, 715)],
        color=C["private_stroke"],
        dashed=True,
        label="Re-enters before clipping in the next round",
        label_xy=(910, 721),
    )

    # Phase 3: right-to-left secure packaging pipeline.
    node(c, 1220, 151, 150, 58, ["Sparse index-value", "representation"], kind="public", size=11.6, leading=13.5)
    node(c, 1000, 151, 190, 58, ["Pad to public fixed budget K", "to limit sparsity metadata leakage"], kind="public", size=10.4, leading=13.0)
    node(c, 810, 151, 160, 58, ["CKKS slot packing"], kind="crypto", size=12.8)
    node(c, 620, 151, 160, 58, ["CKKS encryption"], kind="crypto", size=12.8)
    node(c, 335, 151, 255, 58, ["Attach model version, round ID,", "nonce, timestamp and signature"], kind="crypto", size=11.8, leading=13.8)
    node(c, 80, 151, 225, 58, ["Transmit using mutual TLS"], kind="crypto", size=12.8)

    arrow(c, [(1275, 414), (1275, 230), (1295, 230), (1295, 209)])
    arrow(c, [(1220, 180), (1190, 180)])
    arrow(c, [(1000, 180), (970, 180)])
    arrow(c, [(810, 180), (780, 180)])
    arrow(c, [(620, 180), (590, 180)])
    arrow(c, [(335, 180), (305, 180)])

    c.setFillColor(C["muted"])
    c.setFont(FONT, 9.7)
    c.drawString(50, 37, "Purple: private or DP-derived data     Blue: public configuration/representation     Teal: encrypted transport")
    c.drawRightString(W - 50, 37, "Dashed path: next-round error-feedback residual")

    c.showPage()
    c.save()
    print(PDF_PATH)


if __name__ == "__main__":
    build()
