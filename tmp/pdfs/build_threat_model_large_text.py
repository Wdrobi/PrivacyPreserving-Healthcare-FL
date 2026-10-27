from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output" / "pdf"
OUT.mkdir(parents=True, exist_ok=True)
PDF_PATH = OUT / "healthcare_fl_threat_model_large_text.pdf"

# Compact 9 x 7 inch pages keep type large when figures are placed at report width.
W, H = 648, 504

C = {
    "ink": HexColor("#172536"),
    "muted": HexColor("#667085"),
    "line": HexColor("#C8D1DC"),
    "actor_fill": HexColor("#EAF1FB"),
    "actor_stroke": HexColor("#5277A3"),
    "actor_badge": HexColor("#315F91"),
    "threat_fill": HexColor("#FFF1F0"),
    "threat_stroke": HexColor("#C96862"),
    "threat_badge": HexColor("#A84444"),
    "control_fill": HexColor("#EDF8F0"),
    "control_stroke": HexColor("#5E9870"),
    "control_badge": HexColor("#3C7A50"),
    "white": HexColor("#FFFFFF"),
}


def fonts():
    for name, path in [
        ("UI", r"C:\\Windows\\Fonts\\segoeui.ttf"),
        ("UIB", r"_acl_placeholder_"),
    ]:
        if name == "UIB":
            path = r"C:\\Windows\\Fonts\\seguisb.ttf"
        if Path(path).exists():
            try:
                pdfmetrics.registerFont(TTFont(name, path))
            except Exception:
                pass
    reg = "UI" if "UI" in pdfmetrics.getRegisteredFontNames() else "Helvetica"
    bold = "UIB" if "UIB" in pdfmetrics.getRegisteredFontNames() else "Helvetica-Bold"
    return reg, bold


FONT, BOLD = fonts()


rows = [
    ("HC", "Honest-but-curious aggregation server", "T1", "Gradient reconstruction", "M1", "CKKS encryption + aggregate-only threshold decryption"),
    ("HC", "Honest-but-curious aggregation server", "T2", "Membership and property inference", "M2", "Gradient clipping + DP accountant"),
    ("HC", "Honest-but-curious aggregation server", "T9", "Blockchain metadata leakage", "M9", "Permissioned ledger, pseudonymous IDs and hash-only on-chain records"),
    ("MC", "Malicious or compromised hospital client", "T3", "Model poisoning and backdoor", "M3", "Bound proof, reputation weighting, aggregate validation and rollback"),
    ("MC", "Malicious or compromised hospital client", "T4", "Sybil and reputation manipulation", "M4", "Consortium CA, unique identities and admission control"),
    ("MC", "Malicious or compromised hospital client", "T7", "Client dropout and availability failure", "M7", "Quorum, timeout and dropout-tolerant threshold"),
    ("NET", "External network attacker", "T5", "Tampering, MITM and replay", "M5", "Mutual TLS, signatures, nonce, round ID and timestamp"),
    ("NET", "External network attacker", "T8", "DoS and resource exhaustion", "M8", "Rate limiting, quotas, circuit breaker and monitoring"),
    ("COL", "Colluding participants", "T6", "Key compromise or collusion", "M6", "t-of-n key shares, HSM, rotation and revocation"),
    ("BC", "Faulty administrator or smart-contract vulnerability", "T10", "Smart-contract logic failure", "M10", "Contract audit, multisignature upgrade and emergency pause"),
    ("BC", "Faulty administrator or smart-contract vulnerability", "T12", "Consent violation or revoked-data use", "M12", "Consent registry, purpose binding, revocation and retention enforcement"),
    ("USER", "Malicious inference user", "T11", "Inference extraction and abuse", "M11", "Authentication, query limits, minimal output and inference audit"),
]


def wrap(text, font, size, max_width):
    words = text.split()
    lines, current = [], ""
    for word in words:
        candidate = word if not current else current + " " + word
        if pdfmetrics.stringWidth(candidate, font, size) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def draw_multiline(c, text, x, center_y, max_width, size, leading, max_lines=3):
    lines = wrap(text, FONT, size, max_width)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while pdfmetrics.stringWidth(last + "...", FONT, size) > max_width and last:
            last = last[:-1]
        lines[-1] = last.rstrip() + "..."
    first_y = center_y + ((len(lines) - 1) * leading) / 2 - size * 0.34
    c.setFillColor(C["ink"])
    c.setFont(FONT, size)
    for i, line in enumerate(lines):
        c.drawString(x, first_y - i * leading, line)


def card(c, x, y, w, h, fill, stroke):
    c.setFillColor(fill)
    c.setStrokeColor(stroke)
    c.setLineWidth(1.05)
    c.roundRect(x, y, w, h, 8, fill=1, stroke=1)


def badge(c, code, x, center_y, color, width):
    h = 21
    c.setFillColor(color)
    c.roundRect(x, center_y - h / 2, width, h, h / 2, fill=1, stroke=0)
    c.setFillColor(C["white"])
    c.setFont(BOLD, 8.2)
    c.drawCentredString(x + width / 2, center_y - 2.8, code)


def arrow(c, x1, y, x2):
    c.setStrokeColor(HexColor("#93A0AE"))
    c.setFillColor(HexColor("#93A0AE"))
    c.setLineWidth(1.2)
    c.line(x1, y, x2, y)
    p = c.beginPath()
    p.moveTo(x2, y)
    p.lineTo(x2 - 5.5, y + 3.2)
    p.lineTo(x2 - 5.5, y - 3.2)
    p.close()
    c.drawPath(p, fill=1, stroke=0)


def column_heading(c, x, width, number, title, subtitle, color):
    y = 419
    c.setFillColor(color)
    c.circle(x + 10, y + 1, 10, fill=1, stroke=0)
    c.setFillColor(C["white"])
    c.setFont(BOLD, 7.6)
    c.drawCentredString(x + 10, y - 1.6, number)
    c.setFillColor(C["ink"])
    c.setFont(BOLD, 11.5)
    c.drawString(x + 27, y - 2.4, title)
    c.setFillColor(C["muted"])
    c.setFont(FONT, 6.5)
    c.drawRightString(x + width, y - 1.3, subtitle.upper())


def draw_page(c, page_rows, part, total):
    c.setFillColor(C["white"])
    c.rect(0, 0, W, H, fill=1, stroke=0)

    c.setFillColor(C["ink"])
    c.setFont(BOLD, 20)
    c.drawString(24, 469, "Threat Model and Security Control Mapping")
    c.setFillColor(C["muted"])
    c.setFont(FONT, 8.8)
    c.drawString(24, 451, "Privacy-preserving federated learning for healthcare")
    c.setFont(BOLD, 8.2)
    c.drawRightString(W - 24, 451, f"PANEL {part} OF {total}")
    c.setStrokeColor(C["line"])
    c.setLineWidth(0.65)
    c.line(24, 440, W - 24, 440)

    xa, wa = 24, 150
    xt, wt = 204, 180
    xc, wc = 414, 210
    column_heading(c, xa, wa, "01", "Adversary", "Source", C["actor_badge"])
    column_heading(c, xt, wt, "02", "Threat", "Scenario", C["threat_badge"])
    column_heading(c, xc, wc, "03", "Control", "Mitigation", C["control_badge"])

    row_h, gap, top = 56, 6, 398
    for i, row in enumerate(page_rows):
        actor_code, actor_text, tcode, threat, mcode, control = row
        y = top - i * (row_h + gap) - row_h
        cy = y + row_h / 2

        arrow(c, xa + wa, cy, xt)
        arrow(c, xt + wt, cy, xc)

        card(c, xa, y, wa, row_h, C["actor_fill"], C["actor_stroke"])
        aw = 39 if len(actor_code) > 3 else 34
        badge(c, actor_code, xa + 8, cy, C["actor_badge"], aw)
        draw_multiline(c, actor_text, xa + 8 + aw + 8, cy, wa - aw - 24, 8.7, 10.1, 4)

        card(c, xt, y, wt, row_h, C["threat_fill"], C["threat_stroke"])
        badge(c, tcode, xt + 8, cy, C["threat_badge"], 34)
        draw_multiline(c, threat, xt + 50, cy, wt - 59, 9.9, 11.4, 3)

        card(c, xc, y, wc, row_h, C["control_fill"], C["control_stroke"])
        badge(c, mcode, xc + 8, cy, C["control_badge"], 38)
        draw_multiline(c, control, xc + 54, cy, wc - 63, 9.35, 10.8, 4)

    c.setFillColor(C["muted"])
    c.setFont(FONT, 7.2)
    c.drawString(24, 12, "Reading direction: adversary or failure source  >  threat scenario  >  primary mitigating control")


def build():
    c = canvas.Canvas(str(PDF_PATH), pagesize=(W, H), pageCompression=1)
    c.setTitle("Threat Model and Security Control Mapping - Large Text Edition")
    c.setAuthor("Privacy-Preserving Healthcare FL")
    c.setSubject("Large-text two-panel threat and security-control mapping")
    pages = [rows[:6], rows[6:]]
    for idx, page_rows in enumerate(pages, start=1):
        draw_page(c, page_rows, idx, len(pages))
        c.showPage()
    c.save()
    print(PDF_PATH)


if __name__ == "__main__":
    build()
