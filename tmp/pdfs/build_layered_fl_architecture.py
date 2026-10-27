from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output" / "pdf"
OUT.mkdir(parents=True, exist_ok=True)
PDF_PATH = OUT / "secure_healthcare_fl_layered_architecture.pdf"
W, H = 1600, 1200

C = {
    "ink": HexColor("#172536"),
    "muted": HexColor("#667085"),
    "line": HexColor("#91A0B1"),
    "panel": HexColor("#F8FAFC"),
    "panel_stroke": HexColor("#E1E7EE"),
    "white": HexColor("#FFFFFF"),
    "governance_fill": HexColor("#EAF1FB"),
    "governance_stroke": HexColor("#5277A3"),
    "governance_badge": HexColor("#315F91"),
    "privacy_fill": HexColor("#F0EDFC"),
    "privacy_stroke": HexColor("#7764B4"),
    "privacy_badge": HexColor("#6653A2"),
    "crypto_fill": HexColor("#E7F6F3"),
    "crypto_stroke": HexColor("#4A8D85"),
    "crypto_badge": HexColor("#33766F"),
    "trust_fill": HexColor("#FFF3D8"),
    "trust_stroke": HexColor("#AD7B24"),
    "trust_badge": HexColor("#936716"),
    "secure_fill": HexColor("#ECF7EF"),
    "secure_stroke": HexColor("#5E9870"),
    "secure_badge": HexColor("#377B4C"),
    "reject_fill": HexColor("#FDE8E7"),
    "reject_stroke": HexColor("#B75353"),
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


def rounded(c, x, y, w, h, fill, stroke, radius=9, width=1.05):
    c.setFillColor(fill)
    c.setStrokeColor(stroke)
    c.setLineWidth(width)
    c.roundRect(x, y, w, h, radius, fill=1, stroke=1)


def node(c, x, y, w, h, lines, kind, size=11.6, leading=13.5, bold=False):
    rounded(c, x, y, w, h, C[f"{kind}_fill"], C[f"{kind}_stroke"], radius=9, width=1.15)
    c.setFillColor(C["ink"])
    c.setFont(BOLD if bold else FONT, size)
    first = y + h / 2 + ((len(lines) - 1) * leading) / 2 - size * 0.34
    for i, line in enumerate(lines):
        c.drawCentredString(x + w / 2, first - i * leading, line)


def arrowhead(c, x, y, dx, dy, color):
    length = max((dx * dx + dy * dy) ** 0.5, 0.001)
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    c.setFillColor(color)
    p = c.beginPath()
    p.moveTo(x, y)
    p.lineTo(x - ux * 7 + px * 3.8, y - uy * 7 + py * 3.8)
    p.lineTo(x - ux * 7 - px * 3.8, y - uy * 7 - py * 3.8)
    p.close()
    c.drawPath(p, fill=1, stroke=0)


def arrow(c, points, dashed=False, color=None, width=1.15, label=None, label_xy=None):
    color = color or C["line"]
    c.setStrokeColor(color)
    c.setLineWidth(width)
    c.setLineJoin(1)
    c.setLineCap(1)
    c.setDash(5, 4) if dashed else c.setDash()
    p = c.beginPath()
    p.moveTo(*points[0])
    for point in points[1:]:
        p.lineTo(*point)
    c.drawPath(p, fill=0, stroke=1)
    c.setDash()
    x2, y2 = points[-1]
    x1, y1 = points[-2]
    arrowhead(c, x2, y2, x2 - x1, y2 - y1, color)
    if label and label_xy:
        tw = pdfmetrics.stringWidth(label, BOLD, 8.9)
        c.setFillColor(C["white"])
        c.roundRect(label_xy[0] - 5, label_xy[1] - 4, tw + 10, 15, 6, fill=1, stroke=0)
        c.setFillColor(color)
        c.setFont(BOLD, 8.9)
        c.drawString(label_xy[0], label_xy[1], label)


def panel(c, code, title, y, h, accent, subtitle):
    rounded(c, 50, y, W - 100, h, C["panel"], C["panel_stroke"], radius=14, width=0.9)
    hy = y + h - 22
    c.setFillColor(accent)
    c.roundRect(67, hy - 14, 46, 28, 14, fill=1, stroke=0)
    c.setFillColor(C["white"])
    c.setFont(BOLD, 9.5)
    c.drawCentredString(90, hy - 3.2, code)
    c.setFillColor(C["ink"])
    c.setFont(BOLD, 13.4)
    c.drawString(126, hy - 4.2, title)


def diamond(c, cx, cy, w, h, lines):
    c.setFillColor(C["secure_fill"])
    c.setStrokeColor(C["secure_stroke"])
    c.setLineWidth(1.2)
    p = c.beginPath()
    p.moveTo(cx, cy + h / 2)
    p.lineTo(cx + w / 2, cy)
    p.lineTo(cx, cy - h / 2)
    p.lineTo(cx - w / 2, cy)
    p.close()
    c.drawPath(p, fill=1, stroke=1)
    c.setFillColor(C["ink"])
    c.setFont(BOLD, 10.8)
    c.drawCentredString(cx, cy + 3, lines[0])
    c.drawCentredString(cx, cy - 10, lines[1])


def build():
    c = canvas.Canvas(str(PDF_PATH), pagesize=(W, H), pageCompression=1)
    c.setTitle("Secure Multi-Institutional Healthcare FL Layered Architecture")
    c.setAuthor("Privacy-Preserving Healthcare FL")
    c.setSubject("Governance, privacy, cryptography, aggregation and clinical inference architecture")
    c.setFillColor(C["white"])
    c.rect(0, 0, W, H, fill=1, stroke=0)

    c.setFillColor(C["ink"])
    c.setFont(BOLD, 25.5)
    c.drawString(50, 1156, "Layered Security Architecture")
    c.setFillColor(C["muted"])
    c.setFont(FONT, 12.2)
    c.drawString(50, 1133, "Privacy-preserving federated learning across regulated healthcare institutions")
    c.setStrokeColor(HexColor("#CDD5DF"))
    c.setLineWidth(0.8)
    c.line(50, 1116, W - 50, 1116)

    rounded(c, 410, 1057, 780, 43, HexColor("#F4F7FB"), C["governance_stroke"], radius=12, width=1.2)
    c.setFillColor(C["governance_badge"])
    c.circle(436, 1078.5, 12, fill=1, stroke=0)
    c.setFillColor(C["white"])
    c.setFont(BOLD, 8.4)
    c.drawCentredString(436, 1075.6, "SYS")
    c.setFillColor(C["ink"])
    c.setFont(BOLD, 16.2)
    c.drawCentredString(800, 1073.2, "Secure Multi-Institutional Healthcare FL System")

    layers = [
        ("L0", "Governance, Consent and Compliance", 948, 96, C["governance_badge"], "Identity, policy and lawful-purpose controls"),
        ("L1", "Local Healthcare Data Layer", 842, 96, C["governance_badge"], "Raw clinical data remains inside each hospital"),
        ("L2", "Distributed Cryptographic Setup", 712, 120, C["crypto_badge"], "Collective keys with protected threshold shares"),
        ("L3", "Privacy-Safe Local Training", 562, 140, C["privacy_badge"], "DP, compression, encryption and signed update metadata"),
        ("L4", "Secure Communication and Trust", 432, 120, C["trust_badge"], "Authenticated transport, admission and auditable storage"),
        ("L5", "Secure and Poisoning-Resilient Aggregation", 282, 140, C["secure_badge"], "Quorum, encrypted FedAvg, threshold decryption and validation"),
        ("L6", "Verified Distribution", 176, 96, C["secure_badge"], "Hash-verified delivery of the accepted global model"),
        ("L7", "Privacy-Preserving Clinical Inference", 46, 120, C["crypto_badge"], "Authorized, confidential and output-minimized prediction"),
    ]
    for args in layers:
        panel(c, *args)

    # System-to-governance entry.
    arrow(c, [(800, 1057), (800, 1044)])

    # Cross-layer dependency rails, drawn before nodes.
    arrow(c, [(1125, 958), (1125, 943), (600, 943), (600, 898)], label="Policy", label_xy=(825, 948))
    arrow(c, [(1160, 852), (1480, 852), (1480, 707), (307, 707), (307, 656)], label="Local data", label_xy=(1415, 836))
    arrow(c, [(820, 775), (820, 707), (1135, 707), (1135, 656)], label="Public key", label_xy=(925, 712))
    arrow(c, [(1120, 716), (1510, 716), (1510, 427), (705, 427), (705, 380)], label="Key shares", label_xy=(1438, 600))
    arrow(c, [(1295, 606), (1295, 557), (322, 557), (322, 500)], label="Signed update", label_xy=(760, 562))
    arrow(c, [(1082, 450), (1082, 425), (850, 425)])
    arrow(c, [(1275, 450), (1275, 425), (850, 425)])
    arrow(c, [(850, 425), (322, 425), (322, 380)], label="Off-chain ciphertexts + ledger status", label_xy=(520, 430))
    arrow(c, [(1130, 288), (1450, 288), (1450, 475), (1370, 475)])
    arrow(c, [(1255, 357), (1255, 277), (400, 277), (400, 236)], label="Accepted model", label_xy=(820, 282))
    arrow(c, [(1160, 213), (28, 213), (28, 631), (240, 631)], dashed=True, color=C["privacy_stroke"], label="Repeat L3-L6", label_xy=(45, 636))
    arrow(c, [(1255, 357), (1540, 357), (1540, 171), (715, 171), (715, 120)], label="Accepted model", label_xy=(1460, 300))
    arrow(c, [(635, 958), (15, 958), (15, 171), (515, 171), (515, 120)], label="Consent", label_xy=(25, 963))

    # Internal layer arrows.
    arrow(c, [(480, 983), (1000, 983)])
    arrow(c, [(760, 983), (1000, 983)])
    arrow(c, [(460, 875), (500, 875)])
    arrow(c, [(700, 875), (735, 875)])
    arrow(c, [(965, 875), (1010, 875)])
    arrow(c, [(450, 771), (480, 771)])
    arrow(c, [(670, 771), (720, 798)])
    arrow(c, [(670, 771), (720, 739)])
    arrow(c, [(940, 739), (990, 739)])
    xs = [(375, 390), (535, 550), (680, 695), (865, 880), (1050, 1065), (1205, 1220)]
    for x1, x2 in xs:
        arrow(c, [(x1, 631), (x2, 631)])
    arrow(c, [(615, 606), (615, 604)])
    xs = [(395, 410), (585, 600), (770, 785), (965, 980), (1165, 1180)]
    for x1, x2 in xs:
        arrow(c, [(x1, 475), (x2, 475)])
    arrow(c, [(405, 355), (420, 355)])
    arrow(c, [(605, 355), (620, 355)])
    arrow(c, [(790, 355), (805, 355)])
    arrow(c, [(985, 355), (1000, 355)])
    arrow(c, [(1140, 355), (1160, 377)], label="Yes", label_xy=(1142, 380))
    arrow(c, [(1140, 355), (1160, 328)], color=C["reject_stroke"], label="No", label_xy=(1143, 325))
    arrow(c, [(1255, 357), (1255, 306), (1130, 306)])
    arrow(c, [(1160, 328), (1150, 328), (1150, 306), (1130, 306)])
    arrow(c, [(500, 213), (540, 213)])
    arrow(c, [(740, 213), (780, 213)])
    arrow(c, [(1020, 213), (1060, 213)])
    arrow(c, [(410, 95), (425, 95)])
    arrow(c, [(605, 95), (620, 95)])
    arrow(c, [(810, 95), (825, 95)])
    arrow(c, [(1045, 95), (1060, 95)])

    # L0 nodes.
    node(c, 280, 958, 200, 50, ["Consortium CA", "Hospital identity and roles"], "governance", size=11.2)
    node(c, 510, 958, 250, 50, ["Consent Registry", "purpose, scope, expiry, revocation"], "governance", size=10.9)
    node(c, 1000, 958, 250, 50, ["Governance Policy", "retention, access and incident rules"], "governance", size=10.9)

    # L1 nodes.
    node(c, 280, 852, 180, 46, ["Hospitals A, B, C ... N"], "governance", size=11.7)
    node(c, 500, 852, 200, 46, ["Consent and", "purpose check"], "governance", size=11.4)
    node(c, 735, 852, 230, 46, ["Local preprocessing", "feature extraction and normalization"], "governance", size=10.5)
    node(c, 1010, 852, 300, 46, ["Local healthcare dataset", "raw data never leaves hospital"], "governance", size=11.0)

    # L2 nodes.
    node(c, 280, 748, 170, 46, ["Key rotation", "and revocation"], "crypto", size=11.2)
    node(c, 480, 748, 190, 46, ["Distributed", "key generation"], "crypto", size=11.5)
    node(c, 720, 775, 200, 46, ["Collective CKKS", "public key"], "crypto", size=11.5)
    node(c, 720, 716, 220, 46, ["Threshold secret-key shares", "t-of-n hospitals"], "crypto", size=10.7)
    node(c, 990, 716, 260, 46, ["Key shares protected by", "HSM or secure enclave"], "crypto", size=11.1)

    # L3 nodes.
    node(c, 240, 606, 135, 50, ["Local model", "training"], "privacy", size=11.5)
    node(c, 390, 606, 145, 50, ["Per-client", "gradient clipping"], "privacy", size=11.0)
    node(c, 550, 606, 130, 50, ["Gaussian", "DP noise"], "privacy", size=11.5)
    node(c, 695, 606, 170, 50, ["DP-safe adaptive", "compression"], "privacy", size=11.1)
    node(c, 880, 606, 170, 50, ["Padded sparse encoding", "hide data-dependent", "payload size"], "privacy", size=9.4, leading=10.4)
    node(c, 1065, 606, 140, 50, ["CKKS", "encryption"], "crypto", size=11.6)
    node(c, 1220, 606, 150, 50, ["Digital signature + round ID", "nonce and timestamp"], "trust", size=9.3, leading=11.4)
    node(c, 550, 564, 130, 40, ["Privacy accountant", "epsilon and delta"], "privacy", size=9.8, leading=11.2)

    # L4 nodes.
    node(c, 250, 450, 145, 50, ["Mutual TLS", "secure channel"], "trust", size=11.4)
    node(c, 410, 450, 175, 50, ["Verify certificate, signature,", "nonce and round freshness"], "trust", size=9.4)
    node(c, 600, 450, 170, 50, ["Smart-contract admission", "identity and reputation policy"], "trust", size=9.2)
    node(c, 785, 450, 180, 50, ["Clipping-bound proof or", "trusted execution attestation"], "trust", size=9.5)
    node(c, 980, 450, 185, 50, ["Encrypted updates", "stored off-chain"], "trust", size=10.9)
    node(c, 1180, 450, 190, 50, ["Permissioned ledger stores only", "hash, signature, timestamp", "and status"], "trust", size=8.6, leading=9.8)

    # L5 nodes.
    node(c, 240, 330, 165, 50, ["Minimum-client quorum", "dropout-tolerant collection"], "secure", size=10.2)
    node(c, 420, 330, 185, 50, ["Reputation-aware weighted", "homomorphic FedAvg"], "secure", size=10.2)
    node(c, 620, 330, 170, 50, ["t-of-n threshold decryption", "aggregate only"], "crypto", size=10.4)
    node(c, 805, 330, 180, 50, ["Candidate model validation", "quality, drift and anomaly checks"], "secure", size=9.2)
    diamond(c, 1070, 355, 140, 70, ["Validation", "passed?"])
    node(c, 1160, 357, 190, 40, ["Accept global model"], "secure", size=11.2, bold=True)
    node(c, 1160, 308, 190, 40, ["Reject round, rollback", "and quarantine suspects"], "reject", size=10.3)
    node(c, 950, 288, 180, 36, ["Update reputation", "and audit evidence"], "trust", size=9.4, leading=10.3)

    # L6 nodes.
    node(c, 300, 190, 200, 46, ["Record global-model hash"], "secure", size=11.5)
    node(c, 540, 190, 200, 46, ["Signed secure broadcast"], "secure", size=11.5)
    node(c, 780, 190, 240, 46, ["Hospitals verify", "version and hash"], "secure", size=11.3)
    node(c, 1060, 190, 200, 46, ["Begin next FL round"], "secure", size=11.5)

    # L7 nodes.
    node(c, 230, 70, 180, 50, ["Authenticated", "encrypted request"], "secure", size=11.3)
    node(c, 425, 70, 180, 50, ["Consent and", "authorization check"], "secure", size=11.1)
    node(c, 620, 70, 190, 50, ["Encrypted or", "confidential inference"], "crypto", size=11.1)
    node(c, 825, 70, 220, 50, ["Threshold or enclave decryption", "prediction result only"], "crypto", size=10.2)
    node(c, 1060, 70, 300, 50, ["Output minimization, rate limiting", "and audited clinical decision support"], "secure", size=10.5)

    c.setFillColor(C["muted"])
    c.setFont(FONT, 8.8)
    c.drawString(50, 19, "Color key: governance  |  privacy  |  cryptography  |  trust/audit  |  verified operation  |  rejection")
    c.drawRightString(W - 50, 19, "Long connectors use perimeter rails to preserve layer readability.")

    c.showPage()
    c.save()
    print(PDF_PATH)


if __name__ == "__main__":
    build()
