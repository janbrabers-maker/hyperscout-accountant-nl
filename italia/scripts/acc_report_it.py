#!/usr/bin/env python3
"""Hyperscout Italia books: report builder.

From the ledger tabs read with get_values (displayed values):
  --type month    --period 2026-10            -> monthly overview PDF for Jan (English)
  --type quarter  --period 2026-Q4 [--draft]  -> quarterly overview PDF for Jan and the Excel for Rita (Italian)

data.json:
  {"registrazioni":   rows of Registrazioni!A1:M (header included),
   "fatture_passive": rows of 'Fatture passive'!A1:W,
   "fatture_attive":  rows of 'Fatture attive'!A1:S,
   "debiti":          {"jan": 'Debiti verso soci'!B3, "holding": 'Debiti verso soci'!B4},
   "riporto":         carry-in of the quarter ('IVA trimestrale' row 8),
   "notes":           ["optional line for Jan", ...]}
Prints the paths of the files it wrote.
"""
import argparse, json, os, re
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether

DB = colors.HexColor("#14213D"); BEIGE = colors.HexColor("#EFE8DC"); LINE = colors.HexColor("#C9C2B5")
GREY = colors.HexColor("#5F6368"); RED = colors.HexColor("#DE2E26")
LOGO = [(911,1),(795,1),(774,4),(739,22),(712,57),(706,78),(706,477),(701,490),(683,502),(619,502),(597,487),(450,61),(437,37),(417,18),(391,5),(365,1),(89,1),(50,11),(20,34),(6,59),(0,90),(0,904),(6,935),(34,972),(61,988),(80,992),(516,992),(549,980),(577,956),(594,917),(594,660),(606,645),(615,645),(623,652),(845,979),(875,996),(913,1000),(954,989),(981,967),(999,926),(999,78),(987,45),(966,22),(945,9)]
VAT_HIGH = 0.21
FULL = ["January", "February", "March", "April", "May", "June", "July", "August",
        "September", "October", "November", "December"]

# ------------------------------------------------------------------ parsing
VAT = 0.22; INTEREST = 0.01; MIN_PAY = 100.0
FULL = ["January", "February", "March", "April", "May", "June", "July", "August",
        "September", "October", "November", "December"]

def num(s):
    if s is None: return 0.0
    if isinstance(s, (int, float)): return float(s)
    s = str(s).strip()
    if s in ("", "-"): return 0.0
    neg = s.startswith("(") or s.startswith("-") or s.startswith("−")
    s = re.sub(r"[^0-9.,]", "", s).replace(",", "")
    if not s: return 0.0
    return -float(s) if neg else float(s)

def rows(data, key, width):
    out = []
    for r in (data.get(key) or [])[1:]:
        r = (list(r) + [""] * width)[:width]
        if r[0]: out.append(r)
    return out

def quarter_of(d): return f"{d[:4]}-Q{(int(d[5:7]) - 1) // 3 + 1}"
def q_months(q):
    y, n = q.split("-Q"); n = int(n)
    return [f"{y}-{m:02d}" for m in range((n - 1) * 3 + 1, n * 3 + 1)]
def pay_due(q):
    y, n = map(int, q.split("-Q"))
    return {1: date(y, 5, 16), 2: date(y, 8, 20), 3: date(y, 11, 16), 4: date(y + 1, 3, 16)}[n]
def lipe_due(q):
    y, n = map(int, q.split("-Q"))
    return {1: date(y, 5, 31), 2: date(y, 9, 30), 3: date(y, 11, 30), 4: date(y + 1, 2, 28)}[n]
TRIB = {1: "6031", 2: "6032", 3: "6033", 4: "6099 (with the annual balance)"}

def eur(v, dash=True):
    if abs(v) < 0.005: return "-" if dash else "€ 0.00"
    s = f"€ {abs(v):,.2f}"
    return f"({s})" if v < 0 else s
def esc(t): return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

# ------------------------------------------------------------------ IVA (same rules as the ledger tab 'IVA trimestrale')
def iva(fp, fa, q, carry_in=0.0):
    b = dict(vendite=0.0, rc=0.0, detr=0.0, ue_vend=0.0, ue_acq=0.0, xue_acq=0.0, bollo=0.0, td17=0, rit=0.0)
    for r in fa:
        if quarter_of(r[0]) != q: continue
        b["vendite"] += num(r[7])
        if num(r[7]) == 0 and num(r[5]) > 77.47: b["bollo"] += 2
        if r[6] == "non soggetta art. 7-ter UE": b["ue_vend"] += num(r[5])
    for r in fp:
        if quarter_of(r[0]) != q: continue
        rc = round(num(r[6]) * VAT, 2) if str(r[7]).startswith("reverse") else 0.0
        b["rc"] += rc
        pct = num(r[10]) if str(r[10]).strip() else 100.0
        if r[5] == "Sì": b["detr"] += round((num(r[8]) + rc) * pct / 100, 2)
        if r[7] == "reverse charge UE": b["ue_acq"] += num(r[6])
        if r[7] == "reverse charge extra UE": b["xue_acq"] += num(r[6])
        if str(r[7]).startswith("reverse") and not str(r[21]).strip(): b["td17"] += 1
        b["rit"] += num(r[14])
    b["debito"] = b["vendite"] + b["rc"]; b["saldo_q"] = b["debito"] - b["detr"]
    b["carry_in"] = carry_in; b["saldo"] = b["saldo_q"] + carry_in
    pay = b["saldo"] > MIN_PAY
    b["interessi"] = round(b["saldo"] * INTEREST, 2) if pay else 0.0
    b["versare"] = b["saldo"] + b["interessi"] if pay else 0.0
    b["carry_out"] = 0.0 if pay else b["saldo"]
    return b

def S():
    return dict(h1=ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=15, textColor=DB, leading=19, spaceAfter=2 * mm),
                h2=ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=11, textColor=DB, spaceBefore=5 * mm, spaceAfter=2 * mm),
                body=ParagraphStyle("b", fontName="Helvetica", fontSize=9, leading=12.5),
                small=ParagraphStyle("s", fontName="Helvetica", fontSize=7.5, leading=10, textColor=GREY))

def table(header, body, widths, money_from=1, bold_last=False):
    data = [header] + body
    st = [("FONT", (0, 0), (-1, -1), "Helvetica", 8.6), ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.4),
          ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("BACKGROUND", (0, 0), (-1, 0), DB),
          ("ALIGN", (money_from, 0), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
          ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
          ("LINEBELOW", (0, 1), (-1, -1), 0.3, LINE)]
    if bold_last and body:
        st += [("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 8.6), ("BACKGROUND", (0, -1), (-1, -1), BEIGE)]
    t = Table(data, colWidths=widths, repeatRows=1); t.setStyle(TableStyle(st)); return t

def kpis(items):
    cells = [[Paragraph(f'<font size="7.5" color="#5F6368">{l.upper()}</font><br/><font size="13" color="#14213D"><b>{v}</b></font>',
                        ParagraphStyle("k", leading=16)) for l, v in items]]
    t = Table(cells, colWidths=[174 * mm / len(items)] * len(items))
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), BEIGE), ("TOPPADDING", (0, 0), (-1, -1), 6),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 7), ("LEFTPADDING", (0, 0), (-1, -1), 8),
                           ("LINEAFTER", (0, 0), (-2, -1), 0.6, colors.white)]))
    return t

def build_pdf(path, title, subtitle, story_body, today):
    W, H = A4
    def deco(c, doc):
        c.saveState()
        c.setFillColor(DB); c.rect(0, H - 24 * mm, W, 24 * mm, stroke=0, fill=1)
        c.setFillColor(colors.white); p = c.beginPath(); sx, sy = 13.4 * mm / 1000, 14 * mm / 1000
        p.moveTo(18 * mm + LOGO[0][0] * sx, H - 19 * mm + LOGO[0][1] * sy)
        for x, y in LOGO[1:]: p.lineTo(18 * mm + x * sx, H - 19 * mm + y * sy)
        p.close(); c.drawPath(p, fill=1, stroke=0)
        c.setFont("Helvetica-Bold", 15); c.drawString(35 * mm, H - 13 * mm, "Hyperscout")
        c.setFont("Helvetica", 8.5); c.drawString(35 * mm, H - 18 * mm, "Italia books · contabilità")
        c.setFont("Helvetica-Bold", 9); c.drawRightString(W - 18 * mm, H - 12.5 * mm, title)
        c.setFont("Helvetica", 8.5); c.drawRightString(W - 18 * mm, H - 17.5 * mm, f"Issued {today.strftime('%d %B %Y')}")
        c.setStrokeColor(LINE); c.setLineWidth(0.4); c.line(18 * mm, 14 * mm, W - 18 * mm, 14 * mm)
        c.setFillColor(GREY); c.setFont("Helvetica", 7)
        c.drawString(18 * mm, 9.5 * mm, "Hyperscout Italia S.r.l. · confidential, for Jan only · not the statutory accounts")
        c.drawRightString(W - 18 * mm, 9.5 * mm, f"Page {doc.page}")
        c.restoreState()
    st = S()
    story = [Paragraph(title, st["h1"]), Paragraph(subtitle, st["body"]), Spacer(1, 4 * mm)] + story_body
    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=31 * mm,
                            bottomMargin=20 * mm, title=title, author="Hyperscout Accountant IT")
    doc.build(story, onFirstPage=deco, onLaterPages=deco)

def missing_rows(reg, upto=None):
    return [[r[0], r[1], esc(r[3])[:36], esc(r[4])[:42], eur(num(r[5]))] for r in sorted(reg, key=lambda r: r[0])
            if r[8] == "Fattura mancante" and (upto is None or r[0][:7] <= upto)]

def iva_table(b, q):
    n = int(q[-1])
    body = [["IVA on sales", eur(b["vendite"])], ["IVA on reverse-charge purchases (TD17)", eur(b["rc"])],
            ["IVA deductible on purchases", eur(-b["detr"])], ["Balance this quarter", eur(b["saldo_q"])],
            ["Carried in from the previous quarter", eur(b["carry_in"])], ["1% interest (quarterly regime)", eur(b["interessi"])],
            [f"To pay by {pay_due(q).strftime('%d %b %Y')} (F24 code {TRIB[n]})", eur(b["versare"])]]
    if abs(b["carry_out"]) > 0.005: body.insert(-1, ["Carried to the next quarter (credit, or €100 or less)", eur(b["carry_out"])])
    return table(["", "Amount"], body, [134 * mm, 40 * mm], bold_last=True)

def month_pdf(a, data, today):
    fp, fa, reg = rows(data, "fatture_passive", 23), rows(data, "fatture_attive", 19), rows(data, "registrazioni", 13)
    m = a.period; q = quarter_of(m + "-01")
    in_month = [r for r in reg if r[0][:7] == m]; miss = missing_rows(reg, upto=m)
    b = iva(fp, fa, q, num(data.get("riporto")))
    deb = data.get("debiti") or {}
    st = S(); body = []
    body.append(kpis([("Missing invoices", str(len(miss))), (f"IVA {q} so far", eur(b["saldo"], False)),
                      ("Owed to Jan", eur(num(deb.get("jan")), False)), ("Paid by the Holding", eur(num(deb.get("holding")), False))]))
    for n in data.get("notes") or []: body += [Spacer(1, 2 * mm), Paragraph(esc(n), st["body"])]
    if miss:
        body.append(KeepTogether([Paragraph("Missing invoices: please find these", st["h2"]),
                                  table(["Date", "Paid by", "Counterparty", "Description", "Amount"], miss,
                                        [22 * mm, 16 * mm, 48 * mm, 62 * mm, 26 * mm], money_from=4)]))
    else:
        body += [Paragraph("Missing invoices", st["h2"]), Paragraph("None. Every payment has its invoice.", st["body"])]
    body.append(KeepTogether([Paragraph(f"IVA position {q} so far", st["h2"]), iva_table(b, q)]))
    if b["td17"]: body += [Spacer(1, 2 * mm), Paragraph(f"{b['td17']} reverse-charge invoice(s) still need a TD17 through SdI by the 15th of the month after receipt.", st["body"])]
    per = {}
    for r in in_month: per[r[6] or "Not classified"] = per.get(r[6] or "Not classified", 0.0) + num(r[5])
    if per:
        tb = [[esc(k), eur(v)] for k, v in sorted(per.items(), key=lambda x: x[1])] + [["Net movement", eur(sum(per.values()))]]
        body.append(KeepTogether([Paragraph(f"Bookings in {FULL[int(m[5:]) - 1]} by account (gross)", st["h2"]),
                                  table(["Account", "Amount"], tb, [134 * mm, 40 * mm], bold_last=True)]))
    body += [Spacer(1, 3 * mm), Paragraph("IVA is counted on invoice date. Rita (New Service) files the LIPE, the F24 and the returns.", st["small"])]
    path = os.path.join(a.out, f"Hyperscout_Italia_Riepilogo_mensile_{m}_{today.isoformat()}.pdf")
    build_pdf(path, "Monthly overview", f"Hyperscout Italia S.r.l. · {FULL[int(m[5:]) - 1]} {m[:4]}", body, today)
    return [path]

COST_TYPES = None
def quarter_pdf(a, data, today):
    fp, fa, reg = rows(data, "fatture_passive", 23), rows(data, "fatture_attive", 19), rows(data, "registrazioni", 13)
    q = a.period; y = q[:4]; mon = q_months(q)
    b = iva(fp, fa, q, num(data.get("riporto"))); deb = data.get("debiti") or {}
    inq = lambda d: d[:7] in mon; ytd = lambda d: d[:4] == y and d[:7] <= mon[-1]
    rev = lambda f: sum(num(r[5]) for r in fa if f(r[0]))
    cost = lambda f: sum(num(r[6]) for r in fp if f(r[0]))
    res = [["Revenue (invoiced, net)", eur(rev(inq)), eur(rev(ytd))], ["Costs with invoice (net)", eur(cost(inq)), eur(cost(ytd))],
           ["Result", eur(rev(inq) - cost(inq)), eur(rev(ytd) - cost(ytd))]]
    miss = missing_rows(reg, upto=mon[-1]); st = S(); body = []
    body.append(kpis([("IVA to pay", eur(b["versare"], False)), ("Due", pay_due(q).strftime("%d %b %Y")),
                      ("LIPE by", lipe_due(q).strftime("%d %b %Y")), ("Missing invoices", str(len(miss)))]))
    if a.draft: body += [Spacer(1, 2 * mm), Paragraph("<b>Draft.</b> The last bank days and late invoices are not in yet.", st["body"])]
    for n in data.get("notes") or []: body += [Spacer(1, 2 * mm), Paragraph(esc(n), st["body"])]
    body.append(KeepTogether([Paragraph(f"IVA settlement {q}", st["h2"]), iva_table(b, q)]))
    extra = [["Services sold to EU businesses, art. 7-ter (INTRA-1 quater)", eur(b["ue_vend"])],
             ["Services bought from EU suppliers", eur(b["ue_acq"])], ["Services bought from outside the EU", eur(b["xue_acq"])],
             ["Stamp duty on e-invoices (€2 each)", eur(b["bollo"])], ["Withholding tax on professionals' fees", eur(b["rit"])]]
    body.append(KeepTogether([Paragraph("Other items for Rita", st["h2"]), table(["", "Amount"], extra, [134 * mm, 40 * mm])]))
    body.append(KeepTogether([Paragraph("Result (net of IVA, on invoice date)", st["h2"]),
                              table(["", q, f"Year to date {y}"], res, [94 * mm, 40 * mm, 40 * mm], bold_last=True)]))
    body.append(KeepTogether([Paragraph("Owed by the company", st["h2"]),
                              table(["", "Amount"], [["To Jan (costs he paid)", eur(num(deb.get("jan")))],
                                                     ["To the Holding, if it recharges", eur(num(deb.get("holding")))]], [134 * mm, 40 * mm])]))
    if miss:
        body.append(KeepTogether([Paragraph("Still missing", st["h2"]), table(["Date", "Paid by", "Counterparty", "Description", "Amount"], miss,
                                                                            [22 * mm, 16 * mm, 48 * mm, 62 * mm, 26 * mm], money_from=4)]))
    body += [Spacer(1, 3 * mm), Paragraph("IRES (24%) and IRAP (4.82% in Puglia) are settled yearly by Rita; the result above is year to date only, no estimate.", st["small"])]
    tag = "_BOZZA" if a.draft else ""
    path = os.path.join(a.out, f"Hyperscout_Italia_Riepilogo_trimestrale_{q}{tag}_{today.isoformat()}.pdf")
    build_pdf(path, "Quarterly overview" + (" (draft)" if a.draft else ""), f"Hyperscout Italia S.r.l. · {q}", body, today)
    return [path]

# ------------------------------------------------------------------ Excel for Rita (Italian)
def quarter_xlsx(a, data, today):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    fp, fa, reg = rows(data, "fatture_passive", 23), rows(data, "fatture_attive", 19), rows(data, "registrazioni", 13)
    q = a.period; mon = q_months(q); n = int(q[-1]); deb = data.get("debiti") or {}
    fp_q = sorted(r for r in fp if quarter_of(r[0]) == q); fa_q = sorted(r for r in fa if quarter_of(r[0]) == q)
    reg_q = sorted(r for r in reg if r[0][:7] in mon); miss = sorted(r for r in reg if r[8] == "Fattura mancante" and r[0][:7] <= mon[-1])
    F = "Arial"; HF = Font(name=F, bold=True, color="FFFFFF"); HB = PatternFill("solid", fgColor="14213D")
    BOLD = Font(name=F, bold=True); NORM = Font(name=F); BLUE = Font(name=F, color="0000FF")
    EUR = '€ #,##0.00;(€ #,##0.00);"-"'; DT = "dd/mm/yyyy"
    wb = Workbook(); s = wb.active; s.title = "Riepilogo"
    def d(v):
        try: return date.fromisoformat(v)
        except Exception: return v
    def sheet(name, header, data_rows, money, dates, widths, formulas=None, idx=None):
        ws = wb.create_sheet(name, idx) if idx is not None else wb.create_sheet(name)
        ws.append(header)
        for c in ws[1]: c.font, c.fill, c.alignment = HF, HB, Alignment(wrap_text=True, vertical="center")
        for i, r in enumerate(data_rows, start=2):
            for j, v in enumerate(r, start=1):
                c = ws.cell(row=i, column=j)
                if j in money: c.value = num(v); c.number_format = EUR
                elif j in dates: c.value = d(v) if v else None; c.number_format = DT
                else: c.value = v if v != "" else None
                c.font = NORM
            for j, f in (formulas or {}).items():
                c = ws.cell(row=i, column=j); c.value = f.format(r=i); c.number_format = EUR; c.font = NORM
        for j, w in enumerate(widths, start=1): ws.column_dimensions[get_column_letter(j)].width = w
        ws.freeze_panes = "A2"; return ws
    # Registro acquisti: J (IVA integrata), L (IVA detraibile), M (totale) as formulas
    acq = [r[0:9] + [""] + [r[10] if str(r[10]).strip() else 100] + ["", ""] + r[13:18] + r[19:23] for r in fp_q]
    sheet("Registro acquisti", ["Data fattura", "N. fattura", "Fornitore", "Paese", "P.IVA fornitore", "Intestata alla società", "Imponibile (€)",
                                "Regime IVA", "IVA in fattura (€)", "IVA integrata reverse charge (€)", "% detraibile", "IVA detraibile (€)",
                                "Totale (€)", "Conto", "Ritenuta (€)", "Pagata da", "Pagata il", "File", "Valuta", "Importo in valuta",
                                "TD17 inviato il", "Nota"], acq, {7, 9, 15}, {1, 17, 21},
          [12, 14, 26, 6, 15, 10, 13, 18, 13, 14, 10, 13, 13, 26, 12, 10, 12, 36, 7, 12, 12, 30],
          {10: "=IF(LEFT(H{r},7)=\"reverse\",ROUND(G{r}*'Liquidazione IVA'!$C$3,2),0)",
           12: "=IF(F{r}=\"Sì\",ROUND((I{r}+J{r})*K{r}/100,2),0)", 13: "=G{r}+I{r}"})
    ven = [r[0:8] + [""] + r[9:10] + [""] + r[11:13] + [r[14]] + r[16:19] for r in fa_q]
    sheet("Registro vendite", ["Data fattura", "Numero", "Cliente", "Paese", "P.IVA cliente", "Imponibile (€)", "Regime IVA", "IVA (€)", "Totale (€)",
                               "Natura (SdI)", "Bollo (€)", "Scadenza", "Incassata il", "File", "Valuta", "Importo in valuta", "Nota"],
          ven, {6, 8}, {1, 12, 13}, [12, 12, 26, 6, 16, 13, 22, 12, 13, 10, 9, 12, 12, 36, 7, 12, 30],
          {9: "=F{r}+H{r}+K{r}", 11: "=IF(AND(H{r}=0,F{r}>77.47),2,0)"})
    ws = wb.create_sheet("Liquidazione IVA", 1)
    ws["A1"] = f"Liquidazione IVA {q} (trimestrale per opzione), Hyperscout Italia S.r.l."; ws["A1"].font = Font(name=F, bold=True, size=13)
    for cell, lab, val, fmt in (("3", "Aliquota IVA ordinaria", VAT, "0%"), ("4", "Interessi trimestrali", INTEREST, "0%"), ("5", "Soglia minima versamento (€)", MIN_PAY, EUR),
                                ("6", "Riporto dal trimestre precedente (€)", num(data.get("riporto")), EUR)):
        ws["A" + cell] = lab; ws["C" + cell] = val; ws["C" + cell].number_format = fmt; ws["C" + cell].font = BLUE
    ws["D3"] = "Fonte: DPR 633/1972 art. 16"; ws["D4"] = "Fonte: art. 7 DPR 542/1999"; ws["D5"] = "Fonte: D.Lgs. 1/2024"; ws["D6"] = "Fonte: ledger, tab IVA trimestrale"
    ws.append([]); ws.append(["Voce", "", "Importo (€)"])
    for c in ws[8]: c.font, c.fill = HF, HB
    A, V = "'Registro acquisti'!", "'Registro vendite'!"
    lines = [("IVA a debito su vendite", f"=SUM({V}H:H)"), ("IVA a debito reverse charge (TD17)", f"=SUM({A}J:J)"),
             ("Totale IVA a debito", "=C9+C10"), ("IVA detraibile", f"=SUM({A}L:L)"), ("Saldo del trimestre", "=C11-C12"),
             ("Riporto dal trimestre precedente", "=C6"), ("Saldo da liquidare", "=C13+C14"),
             ("Interessi 1%", "=IF(C15>C5,ROUND(C15*C4,2),0)"), ("IVA da versare", "=IF(C15>C5,C15+C16,0)"),
             ("Riporto al trimestre successivo", "=IF(C15>C5,0,C15)")]
    for l, f in lines:
        ws.append([l, "", f]); ws.cell(ws.max_row, 3).number_format = EUR
        for c in ws[ws.max_row]: c.font = NORM
    for c in ws[17]: c.font = BOLD
    ws.append([])
    info = [("Scadenza versamento", pay_due(q), DT), ("Codice tributo F24", TRIB[n].replace("with the annual balance", "con il saldo annuale"), None),
            ("Scadenza LIPE", lipe_due(q), DT), ("Bollo su fatture elettroniche (€)", f"=SUM({V}K:K)", EUR),
            ("Servizi venduti a clienti UE art. 7-ter (INTRA-1 quater) (€)", f"=SUMIFS({V}F:F,{V}G:G,\"non soggetta art. 7-ter UE\")", EUR),
            ("Servizi acquistati da fornitori UE (€)", f"=SUMIFS({A}G:G,{A}H:H,\"reverse charge UE\")", EUR),
            ("Servizi acquistati da fornitori extra UE (€)", f"=SUMIFS({A}G:G,{A}H:H,\"reverse charge extra UE\")", EUR),
            ("TD17 ancora da inviare (numero)", f"=COUNTIFS({A}H:H,\"reverse*\",{A}U:U,\"\")", "0"),
            ("Ritenute d'acconto (€)", f"=SUM({A}O:O)", EUR)]
    for l, v, fmt in info:
        ws.append([l, "", v]); c = ws.cell(ws.max_row, 3)
        if fmt: c.number_format = fmt
        for c in ws[ws.max_row]: c.font = NORM
    for col, w in zip("ABCD", (52, 4, 22, 36)): ws.column_dimensions[col].width = w
    sheet("Prima nota", ["Data", "Fonte", "Riferimento", "Controparte", "Descrizione", "Importo (€)", "Conto", "N. fattura", "Stato", "Nota"],
          [r[:9] + [r[11]] for r in reg_q], {6}, {1}, [12, 9, 18, 26, 32, 13, 26, 14, 16, 34])
    rit = [[r[0], r[2], r[1], r[6], r[14], r[16]] for r in fp_q if num(r[14]) > 0]
    sheet("Ritenute", ["Data fattura", "Fornitore", "N. fattura", "Imponibile (€)", "Ritenuta (€)", "Pagata il"], rit, {4, 5}, {1, 6}, [12, 26, 14, 13, 13, 12])
    sheet("Fatture mancanti", ["Data", "Fonte", "Controparte", "Descrizione", "Importo (€)", "Nota"],
          [[r[0], r[1], r[3], r[4], r[5], r[11]] for r in miss], {5}, {1}, [12, 9, 26, 32, 13, 40])
    s["A1"] = f"Hyperscout Italia S.r.l., contabilità {q}" + (" (BOZZA)" if a.draft else ""); s["A1"].font = Font(name=F, bold=True, size=14)
    s["A2"] = f"Preparato il {today.strftime('%d/%m/%Y')} per Rita Chiocchia, New Service. Importi su data fattura, al netto dell'IVA salvo indicazione."
    s["A2"].font = Font(name=F, italic=True, color="5F6368")
    tbl = [("Ricavi del trimestre (€)", "=SUM('Registro vendite'!F:F)"), ("Costi con fattura del trimestre (€)", "=SUM('Registro acquisti'!G:G)"),
           ("Risultato del trimestre (€)", "=B4-B5"), (None, None), ("IVA da versare (€)", "='Liquidazione IVA'!C17"),
           ("Scadenza versamento", pay_due(q)), ("Scadenza LIPE", lipe_due(q)), (None, None),
           ("Pagamenti senza fattura", "=MAX(COUNTA('Fatture mancanti'!A:A)-1,0)"), ("Importo senza fattura (€)", "=-SUM('Fatture mancanti'!E:E)"),
           ("Dovuto a Jan Brabers (€)", num(deb.get("jan"))), ("Pagato da Hyperscout Holding B.V. (€)", num(deb.get("holding")))]
    for i, (l, f) in enumerate(tbl, start=4):
        if l is None: continue
        s.cell(i, 1, l).font = NORM; c = s.cell(i, 2, f); c.font = NORM
        c.number_format = DT if isinstance(f, date) else ("0" if l.startswith("Pagamenti") else EUR)
    for ref in ("A6", "B6", "A8", "B8"): s[ref].font = BOLD
    s.cell(14, 3, "Fonte: ledger, tab Debiti verso soci"); s.cell(15, 3, "Dovuto solo se la Holding riaddebita i costi")
    s.column_dimensions["A"].width = 42; s.column_dimensions["B"].width = 18; s.column_dimensions["C"].width = 44
    tag = "_BOZZA" if a.draft else ""
    path = os.path.join(a.out, f"Hyperscout_Italia_IVA_{q}{tag}_{today.isoformat()}.xlsx")
    wb.save(path); return [path]

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--type", required=True, choices=["month", "quarter"])
    p.add_argument("--period", required=True, help="2026-10 for month, 2026-Q4 for quarter")
    p.add_argument("--data", required=True); p.add_argument("--out", default=".")
    p.add_argument("--draft", action="store_true"); p.add_argument("--date", default=None)
    a = p.parse_args(); data = json.load(open(a.data))
    today = date.fromisoformat(a.date) if a.date else date.today()
    files = month_pdf(a, data, today) if a.type == "month" else quarter_pdf(a, data, today) + quarter_xlsx(a, data, today)
    print("\n".join(files))
