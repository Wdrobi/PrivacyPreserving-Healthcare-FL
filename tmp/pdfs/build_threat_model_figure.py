from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output" / "pdf"
OUT.mkdir(parents=True, exist_ok=True)
PDF_PATH = OUT / "healthcare_fl_threat_model_larger_text.pdf"

# Wide, report-ready figure. Coordinates use points.
W, H = 1440, 900

COLORS = {
    "ink": HexColor("#182230"),
    "muted": HexColor("#667085"),
    "line": HexColor("#CBD5E1"),
    "panel": HexColor("#F8FAFC"),
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


def register_fonts():
    candidates = [
        ("SegoeUI", r"C:\\Windows\\Fonts\\segoeui.ttf"),
        ("SegoeUI-Semibold", r"C:\\Windows\\Fonts\\seguisb.ttf"),
    ]
    for name, path in candidates:
        if Path(path).exists():
            try:
                pdfmetrics.registerFont(TTFont(name, path))
            except Exception:
                pass
    regular = "SegoeUI" if "SegoeUI" in pdfmetrics.getRegisteredFontNames() else "Helvetica"
    semibold = "SegoeUI-Semibold" if "SegoeUI-Semibold" in pdfmetrics.getRegisteredFontNames() else "Helvetica-Bold"
    return regular, semibold


FONT, FONT_BOLD = register_fonts()


def round_rect(c, x, y, w, h, fill, stroke, radius=12, line_width=1.2):
    c.setFillColor(fill)
    c.setStrokeColor(stroke)
    c.setLineWidth(line_width)
    c.roundRect(x, y, w, h, radius, fill=1, stroke=1)


def text_lines(c, lines, x, center_y, size=13.4, leading=16.0, color=None, font=None):
    c.setFillColor(color or COLORS["ink"])
    c.setFont(font or FONT, size)
    total = (len(lines) - 1) * leading
    y = center_y + total / 2 - size * 0.34
    for line in lines:
        c.drawString(x, y, line)
        y -= leading


def badge(c, label, x, center_y, fill, w=37, h=24):
    y = center_y - h / 2
    c.setFillColor(fill)
    c.setStrokeColor(fill)
    c.roundRect(x, y, w, h, h / 2, fill=1, stroke=0)
    c.setFillColor(COLORS["white"])
    c.setFont(FONT_BOLD, 10.4)
    c.drawCentredString(x + w / 2, center_y - 3.2, label)


def connector(c, x1, y1, x2, y2, color, width=1.35, arrow=True):
    c.setStrokeColor(color)
    c.setLineWidth(width)
    c.setLineCap(1)
    c.line(x1, y1, x2, y2)
    if arrow:
        c.setFillColor(color)
        c.setStrokeColor(color)
        p = c.beginPath()
        p.moveTo(x2, y2)
        p.lineTo(x2 - 7, y2 + 4)
        p.lineTo(x2 - 7, y2 - 4)
        p.close()
        c.drawPath(p, fill=1, stroke=0)


def header(c, x, y, w, title, subtitle, number, color):
    c.setFillColor(color)
    c.circle(x + 15, y + 5, 15, fill=1, stroke=0)
    c.setFillColor(COLORS["white"])
    c.setFont(FONT_BOLD, 10.5)
    c.drawCentredString(x + 15, y + 1.4, number)
    c.setFillColor(COLORS["ink"])
    c.setFont(FONT_BOLD, 17.5)
    c.drawString(x + 42, y + 1, title)
    c.setFillColor(COLORS["muted"])
    c.setFont(FONT, 10.2)
    c.drawRightString(x + w, y + 2.5, subtitle.upper())


# Grouped by attack source to eliminate edge crossings while retaining labels.
groups = [
    {
        "actor": ("HC", ["Honest-but-curious", "aggregation server"]),
        "rows": [
            ("T1", "Gradient reconstruction", "M1", ["CKKS encryption + aggregate-only", "threshold decryption"]),
            ("T2", "Membership and property inference", "M2", ["Gradient clipping + DP accountant"]),
            ("T9", "Blockchain metadata leakage", "M9", ["Permissioned ledger, pseudonymous IDs", "and hash-only on-chain records"]),
        ],
    },
    {
        "actor": ("MC", ["Malicious or compromised", "hospital client"]),
        "rows": [
            ("T3", "Model poisoning and backdoor", "M3", ["Bound proof, reputation weighting,", "aggregate validation and rollback"]),
            ("T4", "Sybil and reputation manipulation", "M4", ["Consortium CA, unique identities", "and admission control"]),
            ("T7", "Client dropout and availability failure", "M7", ["Quorum, timeout and", "dropout-tolerant threshold"]),
        ],
    },
    {
        "actor": ("NET", ["External network attacker"]),
        "rows": [
            ("T5", "Tampering, MITM and replay", "M5", ["Mutual TLS, signatures, nonce,", "round ID and timestamp"]),
            ("T8", "DoS and resource exhaustion", "M8", ["Rate limiting, quotas,", "circuit breaker and monitoring"]),
        ],
    },
    {
        "actor": ("COL", ["Colluding participants"]),
        "rows": [
            ("T6", "Key compromise or collusion", "M6", ["t-of-n key shares, HSM,", "rotation and revocation"]),
        ],
    },
    {
        "actor": ("BC", ["Faulty administrator or", "smart-contract vulnerability"]),
        "rows": [
            ("T10", "Smart-contract logic failure", "M10", ["Contract audit, multisignature upgrade", "and emergency pause"]),
            ("T12", "Consent violation or revoked-data use", "M12", ["Consent registry, purpose binding,", "revocation and retention enforcement"]),
        ],
    },
    {
        "actor": ("USER", ["Malicious inference user"]),
        "rows": [
            ("T11", "Inference extraction and abuse", "M11", ["Authentication, query limits,", "minimal output and inference audit"]),
        ],
    },
]


def build():
    c = canvas.Canvas(str(PDF_PATH), pagesize=(W, H), pageCompression=1)
    c.setTitle("Threat Model and Security Control Mapping for Privacy-Preserving Healthcare FL")
    c.setAuthor("Privacy-Preserving Healthcare FL")
    c.setSubject("Trust assumptions, threats, and mitigating controls")

    c.setFillColor(COLORS["white"])
    c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setFillColor(COLORS["ink"])
    c.setFont(FONT_BOLD, 26)
    c.drawString(56, 850, "Threat Model and Security Control Mapping")
    c.setFillColor(COLORS["muted"])
    c.setFont(FONT, 12.5)
    c.drawString(56, 827, "Privacy-preserving federated learning for healthcare")
    c.setStrokeColor(COLORS["line"])
    c.setLineWidth(0.8)
    c.line(56, 809, W - 56, 809)

    x_actor, w_actor = 56, 272
    x_threat, w_threat = 390, 418
    x_control, w_control = 870, 514
    head_y = 774
    header(c, x_actor, head_y, w_actor, "Trust & adversary", "Attack source", "01", COLORS["actor_badge"])
    header(c, x_threat, head_y, w_threat, "Threat", "Risk scenario", "02", COLORS["threat_badge"])
    header(c, x_control, head_y, w_control, "Security control", "Primary mitigation", "03", COLORS["control_badge"])

    panel_y, panel_h = 56, 686
    for x, w in [(x_actor, w_actor), (x_threat, w_threat), (x_control, w_control)]:
        c.setFillColor(COLORS["panel"])
        c.setStrokeColor(HexColor("#E6EAF0"))
        c.roundRect(x - 12, panel_y, w + 24, panel_h, 16, fill=1, stroke=1)

    row_h = 47
    row_gap = 6
    group_gap = 11
    top = 724
    y_cursor = top
    threat_boxes = []
    actor_boxes = []

    for group in groups:
        rows = group["rows"]
        group_height = len(rows) * row_h + (len(rows) - 1) * row_gap
        group_top = y_cursor
        group_bottom = y_cursor - group_height
        actor_center = (group_top + group_bottom) / 2
        actor_h = min(64, max(43, group_height - 8))
        actor_y = actor_center - actor_h / 2
        actor_boxes.append((group["actor"], actor_y, actor_h, actor_center))

        for row in rows:
            center_y = y_cursor - row_h / 2
            threat_boxes.append((row, center_y))
            y_cursor -= row_h + row_gap
        y_cursor += row_gap
        y_cursor -= group_gap

    threat_by_actor = {}
    index = 0
    for group in groups:
        threat_by_actor[group["actor"][0]] = []
        for _ in group["rows"]:
            threat_by_actor[group["actor"][0]].append(threat_boxes[index][1])
            index += 1

    for actor, actor_y, actor_h, actor_center in actor_boxes:
        ys = threat_by_actor[actor[0]]
        start_x = x_actor + w_actor
        trunk_x = x_threat - 29
        connector(c, start_x, actor_center, trunk_x, actor_center, HexColor("#91A4BA"), 1.25, arrow=False)
        if len(ys) > 1:
            c.setStrokeColor(HexColor("#91A4BA"))
            c.setLineWidth(1.25)
            c.line(trunk_x, min(ys), trunk_x, max(ys))
        for yy in ys:
            connector(c, trunk_x, yy, x_threat, yy, HexColor("#91A4BA"), 1.25, arrow=True)

    for _, yy in threat_boxes:
        connector(c, x_threat + w_threat, yy, x_control, yy, HexColor("#93A0AE"), 1.35, arrow=True)

    for actor, actor_y, actor_h, actor_center in actor_boxes:
        code, lines = actor
        round_rect(c, x_actor, actor_y, w_actor, actor_h, COLORS["actor_fill"], COLORS["actor_stroke"], radius=12)
        badge_w = 46 if len(code) > 3 else 40
        badge(c, code, x_actor + 14, actor_center, COLORS["actor_badge"], w=badge_w)
        text_lines(c, lines, x_actor + 14 + badge_w + 12, actor_center, size=13.5, leading=16.2)

    for row, center_y in threat_boxes:
        tcode, ttext, mcode, mlines = row
        y = center_y - row_h / 2
        round_rect(c, x_threat, y, w_threat, row_h, COLORS["threat_fill"], COLORS["threat_stroke"], radius=10)
        badge(c, tcode, x_threat + 13, center_y, COLORS["threat_badge"], w=38)
        c.setFillColor(COLORS["ink"])
        c.setFont(FONT, 13.5)
        c.drawString(x_threat + 63, center_y - 4.6, ttext)

        round_rect(c, x_control, y, w_control, row_h, COLORS["control_fill"], COLORS["control_stroke"], radius=10)
        badge(c, mcode, x_control + 13, center_y, COLORS["control_badge"], w=42)
        text_lines(c, mlines, x_control + 68, center_y, size=13.0, leading=15.6)

    c.setFillColor(COLORS["muted"])
    c.setFont(FONT, 10.2)
    c.drawString(56, 29, "Reading direction: adversary or failure source  >  threat scenario  >  primary mitigating control")
    c.drawRightString(W - 56, 29, "Threats are grouped by source to improve traceability and eliminate crossing paths.")

    c.showPage()
    c.save()
    print(PDF_PATH)


if __name__ == "__main__":
    build()
