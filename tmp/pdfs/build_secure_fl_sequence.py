from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output" / "pdf"
OUT.mkdir(parents=True, exist_ok=True)
PDF_PATH = OUT / "secure_federated_learning_sequence.pdf"
W, H = 720, 1220

C = {
    "ink": HexColor("#172536"),
    "muted": HexColor("#667085"),
    "line": HexColor("#7F8FA2"),
    "lifeline": HexColor("#B5C0CD"),
    "white": HexColor("#FFFFFF"),
    "setup": HexColor("#EDF3FA"),
    "setup_stroke": HexColor("#8BA3BF"),
    "round": HexColor("#F2EFFC"),
    "round_stroke": HexColor("#9787C5"),
    "neutral": HexColor("#F8FAFC"),
    "neutral_stroke": HexColor("#D6DEE8"),
    "valid": HexColor("#ECF7EF"),
    "valid_stroke": HexColor("#377B4C"),
    "invalid": HexColor("#FDECEB"),
    "invalid_stroke": HexColor("#B95555"),
    "quorum": HexColor("#E9F6F3"),
    "quorum_stroke": HexColor("#4A8D85"),
    "header": HexColor("#315F91"),
    "number": HexColor("#526579"),
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

participants = {
    "CA": (62, ["Consortium CA"]),
    "H": (210, ["Hospitals A...N"]),
    "B": (360, ["Permissioned", "Ledger"]),
    "S": (510, ["Aggregation", "Server"]),
    "K": (658, ["Threshold Key", "Committee"]),
}


sections = [
    {
        "title": "One-time setup and periodic key rotation",
        "kind": "setup",
        "events": [
            ("msg", "H", "CA", "Register institution and authorized role", False),
            ("msg", "CA", "H", "Issue consortium certificate", True),
            ("msg", "H", "K", "Participate in distributed key generation", False),
            ("msg", "K", "H", "Collective CKKS public key", True),
            ("msg", "K", "H", "Protected t-of-n secret-key shares", True),
        ],
    },
    {
        "title": "Federated learning round r",
        "kind": "round",
        "events": [
            ("msg", "S", "B", "Open signed round with model hash and nonce", False),
            ("msg", "B", "H", "Publish verified round metadata", True),
            ("msg", "S", "H", "Broadcast signed global model", True),
            ("self", "H", "Verify hash, consent and model version", False),
            ("self", "H", "Train, clip, add DP noise and compress", False),
            ("self", "H", "CKKS encrypt and sign update", False),
            ("msg", "H", "S", "Ciphertext + signature + nonce + round ID", False),
        ],
    },
    {
        "title": "Server-side admission and aggregation",
        "kind": "neutral",
        "events": [
            ("self", "S", "Verify identity, signature and freshness", False),
            ("branch_bad", "Invalid identity, replay or policy failure"),
            ("msg", "S", "B", "Record rejection evidence", False),
            ("msg", "S", "H", "Reject update", True),
            ("branch_good", "Else: valid update"),
            ("msg", "S", "B", "Store ciphertext digest and acceptance status", False),
            ("self", "S", "Homomorphic weighted aggregation", False),
        ],
    },
    {
        "title": "Threshold decryption and dropout handling",
        "kind": "quorum",
        "events": [
            ("branch_good", "Quorum reached despite client dropout"),
            ("msg", "S", "K", "Submit aggregate ciphertext only", False),
            ("self", "K", "Collect at least t authorized key shares", False),
            ("msg", "K", "S", "Decrypted aggregate, never individual updates", True),
            ("self", "S", "Validate accuracy, drift and anomaly indicators", False),
            ("branch_bad", "Else: quorum not reached"),
            ("msg", "S", "B", "Mark round incomplete", False),
            ("msg", "S", "H", "Retry without exposing submitted updates", True),
        ],
    },
    {
        "title": "Candidate validation and global-model decision",
        "kind": "neutral",
        "events": [
            ("branch_good", "Candidate passes validation"),
            ("msg", "S", "B", "Commit global-model hash and reputation updates", False),
            ("msg", "S", "H", "Securely broadcast accepted global model", True),
            ("branch_bad", "Else: candidate fails validation"),
            ("msg", "S", "B", "Record rollback and quarantine decision", False),
            ("msg", "S", "H", "Restore last trusted global model", True),
        ],
    },
]


HEADER_H = 25
MSG_H = 28
BRANCH_H = 21
SECTION_GAP = 8
START_Y = 1068


def layout():
    y = START_Y
    blocks = []
    placed = []
    for si, section in enumerate(sections):
        if si:
            y -= SECTION_GAP
        top = y
        placed.append(("section_header", y, section))
        y -= HEADER_H
        for event in section["events"]:
            h = BRANCH_H if event[0].startswith("branch") else MSG_H
            placed.append((event[0], y, event))
            y -= h
        bottom = y
        blocks.append((top + 5, bottom + 3, section))
    return blocks, placed, y


def rounded(c, x, y, w, h, fill, stroke, radius=8, width=0.9):
    c.setFillColor(fill)
    c.setStrokeColor(stroke)
    c.setLineWidth(width)
    c.roundRect(x, y, w, h, radius, fill=1, stroke=1)


def section_style(kind):
    if kind == "setup":
        return C["setup"], C["setup_stroke"], C["header"]
    if kind == "round":
        return C["round"], C["round_stroke"], HexColor("#6D5CAE")
    if kind == "quorum":
        return C["quorum"], C["quorum_stroke"], HexColor("#33766F")
    return C["neutral"], C["neutral_stroke"], C["number"]


def arrowhead(c, x, y, direction, color):
    c.setFillColor(color)
    p = c.beginPath()
    p.moveTo(x, y)
    p.lineTo(x - direction * 7, y + 3.6)
    p.lineTo(x - direction * 7, y - 3.6)
    p.close()
    c.drawPath(p, fill=1, stroke=0)


def number_badge(c, number, y):
    c.setFillColor(C["number"])
    c.circle(20, y + 1, 8.5, fill=1, stroke=0)
    c.setFillColor(C["white"])
    c.setFont(BOLD, 6.6 if number >= 10 else 7.2)
    c.drawCentredString(20, y - 1.4, str(number))


def label(c, text, cx, y, max_width=330):
    size = 10.6
    width = min(max_width, pdfmetrics.stringWidth(text, FONT, size) + 14)
    while pdfmetrics.stringWidth(text, FONT, size) + 14 > max_width and size > 8.6:
        size -= 0.25
        width = min(max_width, pdfmetrics.stringWidth(text, FONT, size) + 14)
    x = max(34, min(W - width - 9, cx - width / 2))
    c.setFillColor(C["white"])
    c.roundRect(x, y - 4, width, 16.5, 6, fill=1, stroke=0)
    c.setFillColor(C["ink"])
    c.setFont(FONT, size)
    c.drawCentredString(x + width / 2, y, text)


def draw_message(c, sender, receiver, text, dashed, y, number):
    x1 = participants[sender][0]
    x2 = participants[receiver][0]
    line_y = y - 14
    number_badge(c, number, line_y)
    c.setStrokeColor(C["line"])
    c.setLineWidth(1.15)
    c.setDash(4, 3) if dashed else c.setDash()
    direction = 1 if x2 > x1 else -1
    c.line(x1, line_y, x2, line_y)
    arrowhead(c, x2, line_y, direction, C["line"])
    c.setDash()
    label(c, text, (x1 + x2) / 2, line_y + 4)


def draw_self(c, who, text, y, number):
    x = participants[who][0]
    line_y = y - 14
    loop_w = 42 if x < 625 else -42
    number_badge(c, number, line_y)
    c.setStrokeColor(C["line"])
    c.setLineWidth(1.15)
    p = c.beginPath()
    p.moveTo(x, line_y + 5)
    p.lineTo(x + loop_w, line_y + 5)
    p.lineTo(x + loop_w, line_y - 5)
    p.lineTo(x, line_y - 5)
    c.drawPath(p, fill=0, stroke=1)
    arrowhead(c, x, line_y - 5, -1 if loop_w > 0 else 1, C["line"])
    label(c, text, x + loop_w / 2, line_y + 4, max_width=310)


def draw_branch(c, text, y, good):
    fill = C["valid"] if good else C["invalid"]
    stroke = C["valid_stroke"] if good else C["invalid_stroke"]
    width = pdfmetrics.stringWidth(text, BOLD, 9.1) + 22
    rounded(c, 32, y - 16, width, 17, fill, stroke, radius=8, width=0.8)
    c.setFillColor(stroke)
    c.setFont(BOLD, 9.1)
    c.drawString(43, y - 11.5, text)
    c.setStrokeColor(stroke)
    c.setLineWidth(0.65)
    c.line(32 + width + 9, y - 7.5, W - 23, y - 7.5)


def draw():
    blocks, placed, final_y = layout()
    c = canvas.Canvas(str(PDF_PATH), pagesize=(W, H), pageCompression=1)
    c.setTitle("Secure Federated Learning Protocol Sequence")
    c.setAuthor("Privacy-Preserving Healthcare FL")
    c.setSubject("Consortium setup, encrypted aggregation, threshold decryption and validation")
    c.setFillColor(C["white"])
    c.rect(0, 0, W, H, fill=1, stroke=0)

    c.setFillColor(C["ink"])
    c.setFont(BOLD, 21.5)
    c.drawString(24, 1180, "Secure Federated Learning Protocol Sequence")
    c.setFillColor(C["muted"])
    c.setFont(FONT, 10.3)
    c.drawString(24, 1158, "Consortium identity, encrypted updates, threshold decryption and auditable model release")
    c.setStrokeColor(HexColor("#CDD5DF"))
    c.setLineWidth(0.7)
    c.line(24, 1142, W - 24, 1142)

    # Section backgrounds are drawn before lifelines.
    for top, bottom, section in blocks:
        fill, stroke, _ = section_style(section["kind"])
        rounded(c, 12, bottom, W - 24, top - bottom, fill, stroke, radius=10, width=0.75)

    # Participant cards and lifelines.
    for code, (x, lines) in participants.items():
        card_w, card_h = 118, 42
        rounded(c, x - card_w / 2, 1090, card_w, card_h, C["white"], C["header"], radius=9, width=1.0)
        c.setFillColor(C["header"])
        c.circle(x - card_w / 2 + 15, 1111, 10, fill=1, stroke=0)
        c.setFillColor(C["white"])
        c.setFont(BOLD, 7.3)
        c.drawCentredString(x - card_w / 2 + 15, 1108.5, code)
        c.setFillColor(C["ink"])
        c.setFont(BOLD, 9.2 if len(lines) == 1 else 8.8)
        if len(lines) == 1:
            c.drawCentredString(x + 10, 1107.7, lines[0])
        else:
            c.drawCentredString(x + 10, 1112.5, lines[0])
            c.drawCentredString(x + 10, 1101.5, lines[1])
        c.setStrokeColor(C["lifeline"])
        c.setLineWidth(0.8)
        c.setDash(3, 4)
        c.line(x, 1090, x, max(36, final_y))
        c.setDash()

    # Events and automatic numbering.
    number = 1
    section_index = 0
    for kind, y, payload in placed:
        if kind == "section_header":
            section = payload
            _, _, accent = section_style(section["kind"])
            c.setFillColor(accent)
            c.circle(27, y - 9, 8.5, fill=1, stroke=0)
            c.setFillColor(C["white"])
            c.setFont(BOLD, 6.8)
            c.drawCentredString(27, y - 11.3, f"{section_index + 1:02d}")
            c.setFillColor(C["ink"])
            c.setFont(BOLD, 11.2)
            c.drawString(42, y - 13, section["title"])
            section_index += 1
        elif kind == "msg":
            _, sender, receiver, text, dashed = payload
            draw_message(c, sender, receiver, text, dashed, y, number)
            number += 1
        elif kind == "self":
            _, who, text, _ = payload
            draw_self(c, who, text, y, number)
            number += 1
        elif kind == "branch_good":
            draw_branch(c, payload[1], y, True)
        elif kind == "branch_bad":
            draw_branch(c, payload[1], y, False)

    c.setFillColor(C["muted"])
    c.setFont(FONT, 8.2)
    c.drawString(24, 18, "Solid arrow: request/action     Dashed arrow: verified response or secure broadcast")
    c.drawRightString(W - 24, 18, "Numbering follows protocol execution order.")

    c.showPage()
    c.save()
    print(PDF_PATH)


if __name__ == "__main__":
    draw()
