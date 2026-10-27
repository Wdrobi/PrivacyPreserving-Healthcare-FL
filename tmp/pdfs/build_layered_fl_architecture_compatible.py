from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output" / "pdf"
OUT.mkdir(parents=True, exist_ok=True)
PDF_PATH = OUT / "secure_healthcare_fl_architecture_report_compatible.pdf"
W, H = 1000, 750

C = {
    "ink": HexColor("#172536"), "muted": HexColor("#667085"),
    "line": HexColor("#8FA0B2"), "white": HexColor("#FFFFFF"),
    "panel": HexColor("#F8FAFC"), "panel_stroke": HexColor("#E1E7EE"),
    "governance_fill": HexColor("#EAF1FB"), "governance_stroke": HexColor("#5277A3"), "governance_badge": HexColor("#315F91"),
    "privacy_fill": HexColor("#F0EDFC"), "privacy_stroke": HexColor("#7764B4"), "privacy_badge": HexColor("#6653A2"),
    "crypto_fill": HexColor("#E7F6F3"), "crypto_stroke": HexColor("#4A8D85"), "crypto_badge": HexColor("#33766F"),
    "trust_fill": HexColor("#FFF3D8"), "trust_stroke": HexColor("#AD7B24"), "trust_badge": HexColor("#936716"),
    "secure_fill": HexColor("#ECF7EF"), "secure_stroke": HexColor("#5E9870"), "secure_badge": HexColor("#377B4C"),
    "reject_fill": HexColor("#FDE8E7"), "reject_stroke": HexColor("#B75353"),
}


def fonts():
    for name, path in [("UI", r"C:\\Windows\\Fonts\\segoeui.ttf"), ("UIB", r"C:\\Windows\\Fonts\\seguisb.ttf")]:
        if Path(path).exists():
            try:
                pdfmetrics.registerFont(TTFont(name, path))
            except Exception:
                pass
    return (
        "UI" if "UI" in pdfmetrics.getRegisteredFontNames() else "Helvetica",
        "UIB" if "UIB" in pdfmetrics.getRegisteredFontNames() else "Helvetica-Bold",
    )


FONT, BOLD = fonts()


def rounded(c, x, y, w, h, fill, stroke, radius=8, width=1.0):
    c.setFillColor(fill); c.setStrokeColor(stroke); c.setLineWidth(width)
    c.roundRect(x, y, w, h, radius, fill=1, stroke=1)


def node(c, x, y, w, h, lines, kind, size=10.2, leading=12.0, bold=False):
    rounded(c, x, y, w, h, C[f"{kind}_fill"], C[f"{kind}_stroke"], 8, 1.05)
    c.setFillColor(C["ink"]); c.setFont(BOLD if bold else FONT, size)
    first = y + h / 2 + (len(lines) - 1) * leading / 2 - size * 0.34
    for i, line in enumerate(lines):
        c.drawCentredString(x + w / 2, first - i * leading, line)


def arrowhead(c, x, y, dx, dy, color):
    length = max((dx * dx + dy * dy) ** 0.5, 0.001); ux, uy = dx / length, dy / length; px, py = -uy, ux
    c.setFillColor(color); p = c.beginPath(); p.moveTo(x, y)
    p.lineTo(x - ux * 6 + px * 3.2, y - uy * 6 + py * 3.2); p.lineTo(x - ux * 6 - px * 3.2, y - uy * 6 - py * 3.2); p.close()
    c.drawPath(p, fill=1, stroke=0)


def arrow(c, points, dashed=False, color=None, label=None, label_xy=None):
    color = color or C["line"]; c.setStrokeColor(color); c.setLineWidth(1.15); c.setLineJoin(1); c.setLineCap(1)
    c.setDash(5, 4) if dashed else c.setDash(); p = c.beginPath(); p.moveTo(*points[0])
    for pt in points[1:]: p.lineTo(*pt)
    c.drawPath(p, fill=0, stroke=1); c.setDash(); x2, y2 = points[-1]; x1, y1 = points[-2]
    arrowhead(c, x2, y2, x2 - x1, y2 - y1, color)
    if label and label_xy:
        tw = pdfmetrics.stringWidth(label, BOLD, 8.3)
        c.setFillColor(C["white"]); c.roundRect(label_xy[0] - 4, label_xy[1] - 3, tw + 8, 14, 5, fill=1, stroke=0)
        c.setFillColor(color); c.setFont(BOLD, 8.3); c.drawString(label_xy[0], label_xy[1], label)


def panel(c, code, title, y, h, accent):
    rounded(c, 24, y, W - 48, h, C["panel"], C["panel_stroke"], 12, 0.85)
    hy = y + h - 19
    c.setFillColor(accent); c.roundRect(38, hy - 12, 36, 24, 12, fill=1, stroke=0)
    c.setFillColor(C["white"]); c.setFont(BOLD, 8.0); c.drawCentredString(56, hy - 2.7, code)
    c.setFillColor(C["ink"]); c.setFont(BOLD, 12.0); c.drawString(84, hy - 3.5, title)


def diamond(c, cx, cy, w, h):
    c.setFillColor(C["secure_fill"]); c.setStrokeColor(C["secure_stroke"]); c.setLineWidth(1.1)
    p = c.beginPath(); p.moveTo(cx, cy + h/2); p.lineTo(cx + w/2, cy); p.lineTo(cx, cy - h/2); p.lineTo(cx - w/2, cy); p.close()
    c.drawPath(p, fill=1, stroke=1); c.setFillColor(C["ink"]); c.setFont(BOLD, 9.2)
    c.drawCentredString(cx, cy + 2, "Validation"); c.drawCentredString(cx, cy - 9.5, "passed?")


def port(c, letter, x, y, direction="out", color=None):
    color = color or C["governance_badge"]
    c.setFillColor(color); c.circle(x, y, 10, fill=1, stroke=0)
    c.setFillColor(C["white"]); c.setFont(BOLD, 8.2); c.drawCentredString(x, y - 2.8, letter)
    if direction == "out": arrow(c, [(x - 24, y), (x - 10, y)], color=color)
    elif direction == "in": arrow(c, [(x + 10, y), (x + 28, y)], color=color)


def page_header(c, panel_no, subtitle):
    c.setFillColor(C["ink"]); c.setFont(BOLD, 21)
    c.drawString(30, 714, "Secure Healthcare FL Layered Architecture")
    c.setFillColor(C["muted"]); c.setFont(FONT, 9.8); c.drawString(30, 693, subtitle)
    c.setFont(BOLD, 9.0); c.drawRightString(W - 30, 693, f"PANEL {panel_no} OF 2")
    c.setStrokeColor(HexColor("#CDD5DF")); c.setLineWidth(0.7); c.line(30, 681, W - 30, 681)


def continuation_key(c):
    c.setFillColor(C["muted"]); c.setFont(FONT, 7.3)
    c.drawString(30, 14, "Cross-panel interfaces:  A signed update -> TLS   B key shares -> threshold decryption   C consent registry -> inference check   D next round -> local training")


def draw_page_one(c):
    page_header(c, 1, "Governance, local data, collective keys and privacy-safe training")
    rounded(c, 260, 642, 480, 28, HexColor("#F4F7FB"), C["governance_stroke"], 9, 1.0)
    c.setFillColor(C["ink"]); c.setFont(BOLD, 13.3); c.drawCentredString(500, 651, "Secure Multi-Institutional Healthcare FL System")
    arrow(c, [(500, 642), (500, 625)])

    panel(c, "L0", "Governance, Consent and Compliance", 520, 105, C["governance_badge"])
    panel(c, "L1", "Local Healthcare Data Layer", 395, 105, C["governance_badge"])
    panel(c, "L2", "Distributed Cryptographic Setup", 235, 140, C["crypto_badge"])
    panel(c, "L3", "Privacy-Safe Local Training", 35, 180, C["privacy_badge"])

    # Internal and cross-layer connectors.
    arrow(c, [(300, 558), (710, 558)]); arrow(c, [(640, 558), (710, 558)])
    arrow(c, [(245, 433), (275, 433)]); arrow(c, [(465, 433), (495, 433)]); arrow(c, [(705, 433), (735, 433)])
    arrow(c, [(220, 292), (250, 292)]); arrow(c, [(430, 292), (500, 315)]); arrow(c, [(430, 292), (500, 263)]); arrow(c, [(710, 263), (750, 263)])
    for a, b in [(155,170),(290,305),(415,430),(560,575),(705,720),(830,845)]: arrow(c, [(a, 142), (b, 142)])
    arrow(c, [(360, 120), (360, 96)])
    arrow(c, [(820, 542), (820, 508), (370, 508), (370, 455)], label="Policy", label_xy=(585, 513))
    arrow(c, [(835, 410), (970, 410), (970, 222), (95, 222), (95, 164)], label="Local data", label_xy=(882, 415))
    arrow(c, [(595, 292), (595, 222), (775, 222), (775, 164)], label="Public key", label_xy=(650, 227))

    # Nodes.
    node(c, 80, 536, 220, 44, ["Consortium CA", "Hospital identity and roles"], "governance", 10.0)
    node(c, 390, 536, 250, 44, ["Consent Registry", "purpose, scope, expiry, revocation"], "governance", 9.7)
    node(c, 710, 536, 220, 44, ["Governance Policy", "retention, access and incident rules"], "governance", 9.6)
    node(c, 55, 411, 190, 44, ["Hospitals A, B, C ... N"], "governance", 10.4)
    node(c, 275, 411, 190, 44, ["Consent and purpose check"], "governance", 10.1)
    node(c, 495, 411, 210, 44, ["Local preprocessing", "feature extraction and normalization"], "governance", 9.2)
    node(c, 735, 411, 200, 44, ["Local healthcare dataset", "raw data never leaves hospital"], "governance", 9.5)
    node(c, 60, 270, 160, 44, ["Key rotation and revocation"], "crypto", 9.9)
    node(c, 250, 270, 180, 44, ["Distributed key generation"], "crypto", 10.1)
    node(c, 500, 293, 190, 44, ["Collective CKKS public key"], "crypto", 10.0)
    node(c, 500, 241, 210, 44, ["Threshold secret-key shares", "t-of-n hospitals"], "crypto", 9.4)
    node(c, 750, 241, 200, 44, ["Key shares protected by", "HSM or secure enclave"], "crypto", 9.6)
    node(c, 35, 120, 120, 44, ["Local model training"], "privacy", 9.8)
    node(c, 170, 120, 120, 44, ["Per-client gradient", "clipping"], "privacy", 9.0)
    node(c, 305, 120, 110, 44, ["Gaussian DP noise"], "privacy", 9.6)
    node(c, 430, 120, 130, 44, ["DP-safe adaptive", "compression"], "privacy", 9.3)
    node(c, 575, 120, 130, 44, ["Padded sparse encoding", "hide data-dependent", "payload size"], "privacy", 7.7, 8.8)
    node(c, 720, 120, 110, 44, ["CKKS encryption"], "crypto", 9.5)
    node(c, 845, 120, 120, 44, ["Digital signature + round ID", "nonce and timestamp"], "trust", 7.9)
    node(c, 305, 55, 110, 41, ["Privacy accountant", "epsilon and delta"], "privacy", 8.2, 9.5)

    # Cross-panel continuation markers.
    port(c, "A", 978, 142, "out", C["trust_badge"])
    port(c, "B", 962, 263, "out", C["crypto_badge"])
    port(c, "C", 660, 546, "out", C["governance_badge"])
    port(c, "D", 22, 142, "in", C["privacy_badge"])
    continuation_key(c)


def draw_page_two(c):
    page_header(c, 2, "Secure transport, resilient aggregation, verified distribution and clinical inference")
    panel(c, "L4", "Secure Communication and Trust", 525, 135, C["trust_badge"])
    panel(c, "L5", "Secure and Poisoning-Resilient Aggregation", 290, 215, C["secure_badge"])
    panel(c, "L6", "Verified Distribution", 165, 105, C["secure_badge"])
    panel(c, "L7", "Privacy-Preserving Clinical Inference", 35, 110, C["crypto_badge"])

    # L4 pipeline and input A.
    for a,b in [(165,180),(325,340),(480,495),(645,660),(800,815)]: arrow(c, [(a, 566), (b, 566)])
    port(c, "A", 23, 566, "in", C["trust_badge"])

    # L5 pipeline and branches.
    for a,b in [(180,195),(350,365),(510,525),(680,690)]: arrow(c, [(a, 400), (b, 400)])
    arrow(c, [(820, 400), (840, 425)], label="Yes", label_xy=(819, 427))
    arrow(c, [(820, 400), (840, 369)], color=C["reject_stroke"], label="No", label_xy=(819, 365))
    arrow(c, [(840, 425), (830, 425), (830, 317), (825, 317)])
    arrow(c, [(840, 369), (830, 369), (830, 317), (825, 317)])
    port(c, "B", 442, 468, "plain", C["crypto_badge"]); arrow(c, [(442,458),(442,422)], color=C["crypto_badge"])

    # L4-to-L5 merge bus and reputation feedback.
    arrow(c, [(730, 544), (730, 515), (520, 515)])
    arrow(c, [(890, 544), (890, 515), (520, 515)])
    arrow(c, [(520, 515), (112, 515), (112, 422)], label="Ciphertexts + ledger status", label_xy=(250, 520))
    arrow(c, [(825, 317), (994, 317), (994, 566), (965, 566)], color=C["trust_stroke"])

    # L6 and L7 pipelines.
    for a,b in [(270,320),(500,550),(740,790)]: arrow(c, [(a, 202), (b, 202)])
    for a,b in [(195,210),(370,385),(555,570),(760,775)]: arrow(c, [(a, 77), (b, 77)])
    arrow(c, [(975, 425), (980, 425), (980, 280), (180, 280), (180, 224)], label="Accepted model", label_xy=(540, 285))
    arrow(c, [(975, 415), (987, 415), (987, 153), (470, 153), (470, 99)], label="Accepted model", label_xy=(790, 158))
    port(c, "C", 290, 118, "plain", C["governance_badge"]); arrow(c, [(290,108),(290,99)], color=C["governance_badge"])
    port(c, "D", 958, 202, "out", C["privacy_badge"])

    # Nodes L4.
    node(c, 35, 544, 130, 44, ["Mutual TLS", "secure channel"], "trust", 9.8)
    node(c, 180, 544, 145, 44, ["Verify certificate, signature,", "nonce and round freshness"], "trust", 8.1)
    node(c, 340, 544, 140, 44, ["Smart-contract admission", "identity and reputation policy"], "trust", 8.2)
    node(c, 495, 544, 150, 44, ["Clipping-bound proof or", "trusted execution attestation"], "trust", 8.2)
    node(c, 660, 544, 140, 44, ["Encrypted updates", "stored off-chain"], "trust", 9.1)
    node(c, 815, 544, 150, 44, ["Permissioned ledger stores only", "hash, signature, timestamp", "and status"], "trust", 7.0, 8.2)

    # Nodes L5.
    node(c, 35, 378, 145, 44, ["Minimum-client quorum", "dropout-tolerant collection"], "secure", 8.7)
    node(c, 195, 378, 155, 44, ["Reputation-aware weighted", "homomorphic FedAvg"], "secure", 8.7)
    node(c, 365, 378, 145, 44, ["t-of-n threshold decryption", "aggregate only"], "crypto", 8.5)
    node(c, 525, 378, 155, 44, ["Candidate model validation", "quality, drift and anomaly checks"], "secure", 8.0)
    diamond(c, 755, 400, 130, 70)
    node(c, 840, 405, 135, 40, ["Accept global model"], "secure", 9.5, bold=True)
    node(c, 840, 349, 135, 40, ["Reject round, rollback", "and quarantine suspects"], "reject", 8.0)
    node(c, 680, 297, 145, 40, ["Update reputation", "and audit evidence"], "trust", 8.5, 10.0)

    # Nodes L6.
    node(c, 90, 180, 180, 44, ["Record global-model hash"], "secure", 9.8)
    node(c, 320, 180, 180, 44, ["Signed secure broadcast"], "secure", 9.8)
    node(c, 550, 180, 190, 44, ["Hospitals verify version and hash"], "secure", 9.5)
    node(c, 790, 180, 150, 44, ["Begin next FL round"], "secure", 9.8)

    # Nodes L7.
    node(c, 35, 55, 160, 44, ["Authenticated encrypted request"], "secure", 9.1)
    node(c, 210, 55, 160, 44, ["Consent and authorization check"], "secure", 9.1)
    node(c, 385, 55, 170, 44, ["Encrypted or confidential inference"], "crypto", 9.0)
    node(c, 570, 55, 190, 44, ["Threshold or enclave decryption", "prediction result only"], "crypto", 8.7)
    node(c, 775, 55, 190, 44, ["Output minimization, rate limiting", "and audited clinical decision support"], "secure", 7.9)
    continuation_key(c)


def build():
    c = canvas.Canvas(str(PDF_PATH), pagesize=(W, H), pageCompression=1)
    c.setTitle("Secure Healthcare FL Architecture - Report Compatible")
    c.setAuthor("Privacy-Preserving Healthcare FL")
    c.setSubject("Two-panel layered architecture with collision-free layout")
    for drawer in (draw_page_one, draw_page_two):
        c.setFillColor(C["white"]); c.rect(0, 0, W, H, fill=1, stroke=0)
        drawer(c); c.showPage()
    c.save(); print(PDF_PATH)


if __name__ == "__main__": build()
