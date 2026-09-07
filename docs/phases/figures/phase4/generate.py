# -*- coding: utf-8 -*-
import html

W = 960
SX, SW = 80, 370          # spine box
EX, EW = 580, 360         # exit box
CX = SX + SW // 2
GAP = 46
FS, FSS = 12, 10.5

PAL = {
  "built": ("#FFFFFF", "#C3CEE0", "#1B2537"),
  "new":   ("#E4EDFD", "#2563EB", "#12244A"),
  "gate":  ("#FDF1DC", "#C08A24", "#5B4110"),
  "good":  ("#E1F3E9", "#2F9E6E", "#14472F"),
  "bad":   ("#FBE7E4", "#C6564A", "#5A211B"),
}
LINE = "#8797B0"
INK_SOFT = "#4C5C77"

def esc(t): return html.escape(t, quote=False)

def bh(n): return 30 + 16 * n

def box(x, y, w, lines, kind, dash=False):
    f, s, t = PAL[kind]
    h = bh(len(lines))
    d = ' stroke-dasharray="4 3"' if dash else ''
    o = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="5" fill="{f}" stroke="{s}" stroke-width="1.4"{d}/>']
    ty = y + 27
    for i, ln in enumerate(lines):
        weight = "600" if i == 0 and len(lines) > 1 else "400"
        o.append(f'<text x="{x + w/2}" y="{ty + i*16}" text-anchor="middle" font-size="{FS}" font-weight="{weight}" fill="{t}">{esc(ln)}</text>')
    return "".join(o), h

def vline(y1, y2, label=None, dash=False):
    d = ' stroke-dasharray="5 4"' if dash else ''
    o = [f'<line x1="{CX}" y1="{y1}" x2="{CX}" y2="{y2-9}" stroke="{LINE}" stroke-width="1.4"{d} marker-end="url(#ar)"/>']
    if label:
        o.append(f'<text x="{CX+11}" y="{(y1+y2)/2+3}" font-size="{FSS}" fill="{INK_SOFT}">{esc(label)}</text>')
    return "".join(o)

def hline(cy, label=None, dash=False):
    d = ' stroke-dasharray="5 4"' if dash else ''
    o = [f'<line x1="{SX+SW}" y1="{cy}" x2="{EX-9}" y2="{cy}" stroke="{LINE}" stroke-width="1.4"{d} marker-end="url(#ar)"/>']
    if label:
        o.append(f'<text x="{(SX+SW+EX)/2}" y="{cy-7}" text-anchor="middle" font-size="{FSS}" fill="{INK_SOFT}">{esc(label)}</text>')
    return "".join(o)

def defs():
    return ('<defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
            f'orient="auto-start-reverse"><path d="M0,1 L9,5 L0,9 z" fill="{LINE}"/></marker></defs>')

PLATE = "#F4F7FC"

def svg(body, h, label):
    return ('<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {W} {h}" role="img" aria-label="{esc(label)}" '
            f'style="width:100%;max-width:{W}px;height:auto;font-family:\'IBM Plex Mono\',ui-monospace,monospace">'
            f'{defs()}<rect x="0" y="0" width="{W}" height="{h}" fill="{PLATE}"/>{body}</svg>')

def spine(rows, label, top=14):
    """rows: list of dicts {lines, kind, down (label on arrow to next), exit:{lines,kind,label,dash}}"""
    y, out = top, []
    for i, r in enumerate(rows):
        b, h = box(SX, y, SW, r["lines"], r["kind"])
        out.append(b)
        if r.get("exit"):
            e = r["exit"]
            eb, eh = box(EX, y + (h - bh(len(e["lines"])))/2, EW, e["lines"], e["kind"], e.get("dash", False))
            out.append(hline(y + h/2, e.get("label"), e.get("dash", False)))
            out.append(eb)
        if i < len(rows) - 1:
            nh = bh(len(rows[i+1]["lines"]))
            out.append(vline(y + h, y + h + GAP, r.get("down")))
            y = y + h + GAP
        else:
            y = y + h
    return svg("".join(out), y + 14, label)

# ---------------- FIGURE 1 : two columns ----------------
def fig1():
    C1X, C2X, CW = 40, 520, 400
    cols = [
      ("TODAY", C1X, [
        (["She selects findings,", "clicks Request all N"], "built"),
        (["Needs items created", "status PENDING"], "built"),
        (["They appear on the needs list"], "built"),
        (["She opens Outlook", "and writes it by hand"], "bad"),
      ]),
      ("AFTER PHASE 4", C2X, [
        (["She selects findings,", "clicks Request all N"], "built"),
        (["Needs items created", "status PENDING"], "built"),
        (["Added to the pending draft", "LP-809"], "new"),
        (["Split by responsible party", "LP-800"], "new"),
        (["AI writes the email", "LP-810"], "new"),
        (["She reviews, edits, sends", "LP-811"], "new"),
        (["status REQUESTED", "requested_at stamped"], "good"),
      ]),
    ]
    out, maxy = [], 0
    for title, x, nodes in cols:
        out.append(f'<text x="{x+CW/2}" y="20" text-anchor="middle" font-size="11" font-weight="600" '
                   f'letter-spacing="1.6" fill="{INK_SOFT}">{title}</text>')
        y = 34
        for i, (lines, kind) in enumerate(nodes):
            b, h = box(x, y, CW, lines, kind)
            out.append(b)
            if i < len(nodes) - 1:
                cx = x + CW/2
                out.append(f'<line x1="{cx}" y1="{y+h}" x2="{cx}" y2="{y+h+GAP-9}" stroke="{LINE}" '
                           f'stroke-width="1.4" marker-end="url(#ar)"/>')
                y = y + h + GAP
            else:
                y = y + h
        maxy = max(maxy, y)
    out.append(f'<line x1="470" y1="34" x2="470" y2="{maxy}" stroke="{LINE}" stroke-width="1" stroke-dasharray="3 5" opacity="0.7"/>')
    return svg("".join(out), maxy + 14, "The Request docs click today versus after Phase 4")

# ---------------- FIGURE 2 : outbound ----------------
def fig2():
    return spine([
      {"lines": ["Verification run leaves", "findings on the file"], "kind": "built", "down": ""},
      {"lines": ["POST findings/request-docs"], "kind": "built"},
      {"lines": ["Is this finding really a request?"], "kind": "gate", "down": "yes",
       "exit": {"lines": ["unidentified_document - the file is here,", "we just cannot type it. Re-classify, LP-801"], "kind": "new",
                "label": "no"}},
      {"lines": ["Which documents resolve it?", "requested_documents, else the spec"], "kind": "built"},
      {"lines": ["Group by DOCUMENT, not finding", "9 findings become 5 documents"], "kind": "built"},
      {"lines": ["Already PENDING on this file?"], "kind": "gate", "down": "no",
       "exit": {"lines": ["Skip - a borrower must", "never be asked twice"], "kind": "bad", "label": "yes"}},
      {"lines": ["create_needs_item", "PENDING · origin FINDING · titled by document"], "kind": "built"},
      {"lines": ["Who is responsible?  LP-800 lookup"], "kind": "gate", "down": "borrower",
       "exit": {"lines": ["You order it: appraisal, credit report", "Title company / employer / CPA"], "kind": "new",
                "label": "not the borrower"}},
      {"lines": ["Borrower section of the pending draft", "LP-809"], "kind": "new"},
      {"lines": ["AI drafts subject, sections, closing", "LP-810"], "kind": "new"},
      {"lines": ["Compliance scanner - deterministic,", "not a prompt instruction"], "kind": "gate", "down": "clean",
       "exit": {"lines": ["Blocks rates, APR, approved/denied,", "wire and account numbers. One retry,", "then the plain template"], "kind": "new",
                "label": "it trips"}},
      {"lines": ["She reviews and edits"], "kind": "new"},
      {"lines": ["Send - Reply-To set to the file address"], "kind": "new"},
      {"lines": ["Needs item becomes REQUESTED", "requested_at stamped, reminder clock starts"], "kind": "good"},
    ], "How a Request docs click becomes a sent email")

# ---------------- FIGURE 3 : route A ----------------
def fig3():
    return spine([
      {"lines": ["Borrower hits Reply with 3 PDFs"], "kind": "built"},
      {"lines": ["To: lf-8f3a91c2@in.mortgageboss.ai"], "kind": "new"},
      {"lines": ["SES receipt rule", "MX on the inbound-only subdomain"], "kind": "new"},
      {"lines": ["Raw .eml into OUR S3 bucket", "SSE-KMS, durable before our code runs"], "kind": "new"},
      {"lines": ["EventBridge to SQS to Celery"], "kind": "new"},
      {"lines": ["Routing confidence: CERTAIN", "the token IS the loan file"], "kind": "good"},
    ], "Route A: a reply to the per-file address")

# ---------------- FIGURE 4 : route B ----------------
def fig4():
    return spine([
      {"lines": ["Borrower emails processing@herco.com"], "kind": "built", "down": "copy",
       "exit": {"lines": ["Her inbox - unchanged,", "she keeps every message"], "kind": "built", "label": "original"}},
      {"lines": ["Admin rule", "Workspace routing rule, or M365 mail flow rule"], "kind": "new"},
      {"lines": ["To: co-7f2a19@in.mortgageboss.ai"], "kind": "new"},
      {"lines": ["SES to S3 to SQS to Celery"], "kind": "new"},
      {"lines": ["Which loan file?", "Nothing in the message says"], "kind": "gate",
       "exit": {"lines": ["The routing ladder - figure 5"], "kind": "new", "label": "resolve"}},
      {"lines": ["Is the sender real?", "SPF always fails across a forward"], "kind": "gate",
       "exit": {"lines": ["Read the ORIGINAL hop instead:", "Authentication-Results, ARC, surviving DKIM"],
                "kind": "new", "label": "evaluate"}},
      {"lines": ["Trust gate - figure 6"], "kind": "new"},
    ], "Route B: mail sent to the processor's own address")

# ---------------- FIGURE 5 : routing ladder ----------------
def fig5():
    return spine([
      {"lines": ["Inbound message"], "kind": "built", "down": ""},
      {"lines": ["1.  Address carries an lf- token?"], "kind": "gate", "down": "no",
       "exit": {"lines": ["CERTAIN"], "kind": "good", "label": "yes"}},
      {"lines": ["2.  Reply chain matches a", "Message-ID we generated?"], "kind": "gate", "down": "no",
       "exit": {"lines": ["CERTAIN"], "kind": "good", "label": "yes"}},
      {"lines": ["3.  Our LF reference tag in the footer?"], "kind": "gate", "down": "no",
       "exit": {"lines": ["HIGH"], "kind": "good", "label": "yes"}},
      {"lines": ["4.  Sender is a known party", "on exactly one open file?"], "kind": "gate", "down": "no",
       "exit": {"lines": ["MEDIUM"], "kind": "built", "label": "yes"}},
      {"lines": ["5.  Loan number or display_id", "in the subject line?"], "kind": "gate", "down": "no",
       "exit": {"lines": ["MEDIUM"], "kind": "built", "label": "yes"}},
      {"lines": ["6.  AI ranks the open files", "by sender and content"], "kind": "gate", "down": "nothing fits",
       "exit": {"lines": ["LOW - suggestion only,", "never auto-accepts"], "kind": "built", "label": "a candidate"}},
      {"lines": ["UNROUTED - company triage queue.", "Always visible, never cross-tenant"], "kind": "new"},
    ], "The routing ladder: six signals, best first")

# ---------------- FIGURE 6 : trust gate ----------------
def fig6():
    return spine([
      {"lines": ["Routed message and its attachments"], "kind": "built", "down": "PASS"},
      {"lines": ["virus_verdict"], "kind": "gate", "down": "PASS or GRAY",
       "exit": {"lines": ["REJECT - never rendered,", "never extracted, kept for audit"], "kind": "bad", "label": "FAIL"}},
      {"lines": ["dmarc_verdict"], "kind": "gate", "down": "PASS",
       "exit": {"lines": ["REJECT"], "kind": "bad", "label": "FAIL and p=reject"}},
      {"lines": ["Routing CERTAIN, sender a known party,", "and auto-accept switched on for this file?"],
       "kind": "gate", "down": "no - the default",
       "exit": {"lines": ["Auto-accept"], "kind": "good", "label": "yes"}},
      {"lines": ["TRIAGE QUEUE", "sender, auth badge, thumbnails,", "suggested file / type / need"], "kind": "new"},
      {"lines": ["She chooses"], "kind": "gate", "down": "Accept or Reassign",
       "exit": {"lines": ["Rejected - never touches the file"], "kind": "bad", "label": "Reject"}},
      {"lines": ["create_document", "upload_source = borrower_inbox · uploader null"], "kind": "good"},
      {"lines": ["A current document of this type", "already on the file?"], "kind": "gate", "down": "no",
       "exit": {"lines": ["possible_duplicate = true", "surfaced gently, replaces nothing"], "kind": "new", "label": "yes"}},
      {"lines": ["Existing pipeline, unchanged:", "classify, extract, needs update", "under the per-file Redis lock"], "kind": "built"},
    ], "The approval gate: reject, triage, or auto-accept")

# ---------------- FIGURE 7 : attachment safety ----------------
def fig7():
    return spine([
      {"lines": ["MIME part", "recursed into forwards, depth capped at 5"], "kind": "new", "down": ""},
      {"lines": ["Magic bytes match the declared", "type and the extension?"], "kind": "gate", "down": "yes",
       "exit": {"lines": ["Quarantine", "a .pdf that sniffs as ZIP is an attack"], "kind": "bad", "label": "no"}},
      {"lines": ["Is it an archive?  zip / 7z / rar"], "kind": "gate", "down": "no",
       "exit": {"lines": ["Quarantine", "ask for the files individually"], "kind": "bad", "label": "yes"}},
      {"lines": ["Malware scan result arrived, and clean?"], "kind": "gate", "down": "clean",
       "exit": {"lines": ["Quarantine", "a threat, or no result in N minutes"], "kind": "bad", "label": "no"}},
      {"lines": ["PDF encrypted?"], "kind": "gate", "down": "no",
       "exit": {"lines": ["No AV can read an encrypted PDF.", "Ask her for the password,", "then re-enter at the top"], "kind": "new",
                "label": "yes"}},
      {"lines": ["pikepdf strips /JS, /OpenAction,", "/EmbeddedFile, /Launch, /XFA"], "kind": "new"},
      {"lines": ["Rasterize every page to an image"], "kind": "new"},
      {"lines": ["OCR and extraction read", "ONLY the rasterized image"], "kind": "good"},
    ], "Making an emailed attachment safe to read")

# ---------------- FIGURE 8 : state machine ----------------
def fig8():
    o, H = [], 336
    bw, bh_ = 168, 46
    row = 132
    xs = {"PENDING": 40, "REQUESTED": 268, "RECEIVED": 496, "VERIFIED": 724}
    kinds = {"PENDING": "built", "REQUESTED": "new", "RECEIVED": "built", "VERIFIED": "good"}
    for name, x in xs.items():
        f, s, t = PAL[kinds[name]]
        o.append(f'<rect x="{x}" y="{row}" width="{bw}" height="{bh_}" rx="5" fill="{f}" stroke="{s}" stroke-width="1.4"/>')
        o.append(f'<text x="{x+bw/2}" y="{row+28}" text-anchor="middle" font-size="{FS}" font-weight="600" fill="{t}">{name}</text>')
    def arrow(x1, y1, x2, y2, lab=None, dash=False, above=True):
        d = ' stroke-dasharray="5 4"' if dash else ''
        o.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{LINE}" stroke-width="1.4"{d} marker-end="url(#ar)"/>')
        if lab:
            o.append(f'<text x="{(x1+x2)/2}" y="{(y1+y2)/2 + (-8 if above else 16)}" text-anchor="middle" font-size="{FSS}" fill="{INK_SOFT}">{esc(lab)}</text>')
    arrow(208, row+23, 259, row+23, "sent")
    arrow(436, row+23, 487, row+23, "a document arrives")
    arrow(664, row+23, 715, row+23, "passes")
    # labels under the first two arrows
    o.append(f'<text x="233" y="{row+40}" text-anchor="middle" font-size="{FSS}" fill="{INK_SOFT}">LP-811</text>')
    # REJECTED below RECEIVED
    f, s, t = PAL["bad"]
    o.append(f'<rect x="496" y="230" width="{bw}" height="{bh_}" rx="5" fill="{f}" stroke="{s}" stroke-width="1.4"/>')
    o.append(f'<text x="{496+bw/2}" y="258" text-anchor="middle" font-size="{FS}" font-weight="600" fill="{t}">REJECTED</text>')
    arrow(580, row+bh_, 580, 221, None)
    o.append(f'<text x="590" y="205" font-size="{FSS}" fill="{INK_SOFT}">doc failed - still open</text>')
    # WAIVED below PENDING
    f, s, t = PAL["built"]
    o.append(f'<rect x="40" y="230" width="{bw}" height="{bh_}" rx="5" fill="{f}" stroke="{s}" stroke-width="1.4"/>')
    o.append(f'<text x="{40+bw/2}" y="258" text-anchor="middle" font-size="{FS}" font-weight="600" fill="{t}">WAIVED</text>')
    arrow(124, row+bh_, 124, 221, None)
    o.append(f'<text x="134" y="205" font-size="{FSS}" fill="{INK_SOFT}">does not apply</text>')
    # reminder loop above REQUESTED (dotted)
    f, s, t = PAL["new"]
    o.append(f'<rect x="236" y="34" width="264" height="{bh_}" rx="5" fill="{f}" stroke="{s}" stroke-width="1.4" stroke-dasharray="4 3"/>')
    o.append(f'<text x="368" y="54" text-anchor="middle" font-size="{FS}" font-weight="600" fill="{t}">Reminder suggestion  LP-814</text>')
    o.append(f'<text x="368" y="70" text-anchor="middle" font-size="{FSS}" fill="{t}">she clicks it, reviews, sends</text>')
    arrow(320, row-2, 300, 89, None, dash=True)
    o.append(f'<text x="196" y="112" font-size="{FSS}" fill="{INK_SOFT}">3 days, nothing</text>')
    arrow(420, 89, 440, row-2, None, dash=True)
    o.append(f'<text x="452" y="112" font-size="{FSS}" fill="{INK_SOFT}">clock restarts</text>')
    # back arc VERIFIED -> PENDING
    o.append(f'<path d="M808,{row+bh_} V312 H16 V{row+23} H{40-9}" fill="none" stroke="{LINE}" stroke-width="1.4" marker-end="url(#ar)"/>')
    o.append(f'<text x="440" y="304" text-anchor="middle" font-size="{FSS}" fill="{INK_SOFT}">the document is superseded - the need reopens</text>')
    return svg("".join(o), H, "The needs item state machine and the reminder loop")

FIGS = {"F1": fig1(), "F2": fig2(), "F3": fig3(), "F4": fig4(),
        "F5": fig5(), "F6": fig6(), "F7": fig7(), "F8": fig8()}
import json
json.dump(FIGS, open('/home/claude/fig/figs.json', 'w'))
print({k: len(v) for k, v in FIGS.items()})
