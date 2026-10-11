# Abgleich web page. Start it with:  python -m streamlit run app.py

from html import escape
from pathlib import Path

import streamlit as st

from checker import GERMAN, PAYMENT_FIELDS, STOP_PAYMENT_FIELDS, check_invoice, draft_supplier_email

# The sample invoices: button text -> (file, what the sample shows)
SAMPLES = {
    "Sample: buyer name differs": (
        Path("samples/good_invoice.pdf"),
        "A real invoice made on a free invoicing website. Its PDF and XML disagree about the buyer.",
    ),
    "Sample: bank account changed": (
        Path("samples/fraud_example.pdf"),
        "A test invoice where someone changed the bank account inside the XML. The PDF still shows the real one.",
    ),
}
UPLOAD = "Upload a PDF"
REPO = "https://github.com/prajwal-shet-fpa-ai/abgleich"

st.set_page_config(page_title="Abgleich: is this invoice safe to book and pay?", page_icon="🧾", layout="centered")

# ---------- Look and feel ----------

st.html("""
<style>
:root {
  --paper: #EEF2EC; --sheet: #FBFCFA; --ink: #1D2B36; --ink-soft: #55646E;
  --rule: #C9D3CC; --ledger: #2E6B4F; --stamp-red: #B3261E; --amber: #9A5B13;
}
[data-testid="stDecoration"] { display: none; }
.block-container { padding-top: 2.2rem; }

.ab-brand { display: flex; align-items: baseline; gap: .6rem; margin-bottom: 1.6rem; }
.ab-brand b { font-size: 1.15rem; font-weight: 800; letter-spacing: -.01em; color: var(--ink); }
.ab-brand span { color: var(--ink-soft); font-size: .95rem; }

.ab-hero { display: grid; grid-template-columns: 1.7fr 1fr; gap: 1.6rem; align-items: center; margin-bottom: 1.2rem; }
.ab-hero h1 { font-size: 2.35rem; line-height: 1.08; font-weight: 800; letter-spacing: -.025em;
  color: var(--ink); margin: 0 0 .9rem 0; padding: 0; }
.ab-hero p { color: var(--ink-soft); font-size: 1.05rem; line-height: 1.55; margin: 0; max-width: 34rem; }

.ab-sheets { position: relative; height: 225px; }
.ab-xml { position: absolute; right: 0; top: 0; width: 92%; height: 150px; background: var(--ink);
  color: #CFE3D6; font-family: "IBM Plex Mono", monospace; font-size: .64rem; line-height: 1.65;
  padding: .8rem 1rem; border-radius: 4px; overflow: hidden; white-space: nowrap; }
.ab-xml i { color: #8FB7A0; font-style: normal; }
.ab-pdf { position: absolute; left: 0; bottom: 0; width: 70%; height: 118px; background: var(--sheet);
  border: 1px solid var(--rule); border-radius: 4px; padding: .85rem .9rem;
  box-shadow: 0 14px 30px rgba(29, 43, 54, .16); }
.ab-pdf .t { font-weight: 700; font-size: .74rem; color: var(--ink); white-space: nowrap; }
.ab-pdf .bar { height: 6px; background: #DCE3DD; border-radius: 3px; margin: .45rem 0; }
.ab-pdf .sum { position: absolute; right: .9rem; bottom: .8rem; font-weight: 700; font-size: .82rem; color: var(--ink); }
.ab-tag { position: absolute; font-size: .66rem; font-weight: 700; padding: .1rem .4rem; border-radius: 3px; }
.ab-xml .ab-tag { right: .6rem; bottom: .6rem; background: #2F4352; color: #CFE3D6; }
.ab-pdf .ab-tag { left: .9rem; bottom: .8rem; background: #E2E9E3; color: var(--ink-soft); }

.ab-result { display: flex; align-items: center; gap: 1.8rem; flex-wrap: wrap;
  background: var(--sheet); border: 1px solid var(--rule); border-radius: 6px; padding: 1.4rem 1.6rem; margin: .4rem 0 .6rem 0; }
.ab-stamp { display: inline-block; color: var(--c); font-weight: 800; font-size: 1.75rem; letter-spacing: .08em;
  text-transform: uppercase; padding: .3rem 1rem; border: 4px solid currentColor; border-radius: 6px;
  outline: 2px solid currentColor; outline-offset: 3px; transform: rotate(-5deg); opacity: .9;
  animation: ab-land .3s cubic-bezier(.2, .9, .3, 1.25) both; white-space: nowrap; }
@keyframes ab-land { from { transform: rotate(-5deg) scale(1.7); opacity: 0; } to { transform: rotate(-5deg) scale(1); opacity: .9; } }
@media (prefers-reduced-motion: reduce) { .ab-stamp { animation: none; } }
.ab-result-text { flex: 1; min-width: 16rem; }
.ab-result-text strong { display: block; font-size: 1.1rem; color: var(--ink); margin-bottom: .25rem; }
.ab-result-text span { color: var(--ink-soft); line-height: 1.5; }
.ab-result-text .ab-caution { display: block; margin-top: .5rem; color: var(--amber); font-weight: 600; font-size: .92rem; }
.ab-result-text .ab-note { display: block; margin-top: .45rem; }

.ab-h { font-size: 1.3rem; font-weight: 700; letter-spacing: -.01em; color: var(--ink); margin: .9rem 0 .15rem 0; padding: 0; }
.ab-sub { color: var(--ink-soft); font-size: .92rem; margin: 0 0 .7rem 0; }
.ab-alert { background: rgba(179, 38, 30, .07); border-left: 4px solid var(--stamp-red); color: var(--ink);
  padding: .8rem 1rem; border-radius: 0 6px 6px 0; margin: 0 0 .8rem 0; line-height: 1.5; }

.ab-wrap { overflow-x: auto; margin-bottom: .6rem; }
.ab-table { width: 100%; border-collapse: collapse; font-size: .93rem; background: var(--sheet);
  border: 1px solid var(--rule); border-radius: 6px; }
.ab-table th { text-align: left; font-weight: 600; color: var(--ink-soft); font-size: .85rem;
  padding: .7rem .8rem; border-bottom: 2px solid var(--ink); }
.ab-table td { padding: .65rem .8rem; border-bottom: 1px solid var(--rule); vertical-align: top; color: var(--ink); }
.ab-table tr:last-child td { border-bottom: none; }
.ab-table .de { display: block; color: var(--ink-soft); font-size: .78rem; margin-top: .1rem; }
.ab-table code { font-family: "IBM Plex Mono", monospace; font-size: .82rem; background: #E8EEE9;
  color: var(--ink); padding: .1rem .35rem; border-radius: 3px; }
.ab-table tr.bad td { background: rgba(179, 38, 30, .06); }
.ab-table tr.bad td:first-child { box-shadow: inset 4px 0 0 var(--stamp-red); }
.ab-status { font-weight: 600; white-space: nowrap; }
.ab-iban { white-space: nowrap; }
.ab-table td.ab-ok { color: var(--ledger); } .ab-table td.ab-bad { color: var(--stamp-red); }
.ab-table td.ab-warn { color: var(--amber); } .ab-table td.ab-note { color: var(--ink-soft); }
.ab-note { color: var(--ink-soft); font-size: .88rem; }
.ab-empty { border: 1.5px dashed var(--rule); border-radius: 6px; padding: 1.1rem 1.3rem;
  color: var(--ink-soft); background: var(--sheet); }

.ab-foot { margin-top: 2.4rem; padding-top: 1rem; border-top: 1px solid var(--rule);
  color: var(--ink-soft); font-size: .85rem; }
.ab-foot a { color: var(--ledger); }

@media (max-width: 640px) {
  .ab-hero { grid-template-columns: 1fr; }
  .ab-hero h1 { font-size: 2.05rem; }
  .ab-sheets { height: 215px; }
  .ab-result { padding: 1.1rem; gap: 1.1rem; }
  .ab-stamp { font-size: 1.4rem; }

  /* On phones each row of the table becomes a small card */
  .ab-table thead { display: none; }
  .ab-table, .ab-table tbody { display: block; }
  .ab-table tr { display: grid; grid-template-columns: 1fr auto; column-gap: .8rem;
    padding: .7rem .9rem; border-bottom: 1px solid var(--rule); }
  .ab-table tr:last-child { border-bottom: none; }
  .ab-table td { display: block; padding: 0; border: none; background: none; }
  .ab-table td:nth-child(1) { grid-column: 1; grid-row: 1; margin-bottom: .45rem; }
  .ab-table td:nth-child(4) { grid-column: 2; grid-row: 1; }
  .ab-table td:nth-child(2), .ab-table td:nth-child(3) { grid-column: 1 / -1; display: flex; align-items: baseline;
    font-size: .88rem; margin-top: .2rem; }
  .ab-table td[data-label]::before { content: attr(data-label); flex: 0 0 2.6rem;
    color: var(--ink-soft); font-size: .75rem; font-weight: 600; }
  .ab-val { min-width: 0; }
  .ab-table tr.bad { background: rgba(179, 38, 30, .06); box-shadow: inset 4px 0 0 var(--stamp-red); }
  .ab-table tr.bad td, .ab-table tr.bad td:first-child { background: none; box-shadow: none; }
}
</style>
""")

# ---------- Hero ----------

st.html("""
<div class="ab-brand"><b>Abgleich</b><span>checks German ZUGFeRD invoices</span></div>
<div class="ab-hero">
  <div>
    <h1>Does the PDF say what the XML says?</h1>
    <p>A ZUGFeRD invoice has two layers. People read the PDF, but for input VAT only the hidden
    XML counts, and some payment software takes the bank details from it too. Abgleich reads
    both layers and tells you if the invoice is safe to book and safe to pay.</p>
  </div>
  <div class="ab-sheets" aria-hidden="true">
    <div class="ab-xml"><span class="ab-tag">XML</span>
      &lt;ram:ID&gt;<i>RE-0001-2026</i>&lt;/ram:ID&gt;<br>
      &lt;ram:BuyerTradeParty&gt;<br>
      &nbsp;&nbsp;&lt;ram:Name&gt;<i>Beispiel Handel GmbH</i>&lt;/ram:Name&gt;<br>
      &lt;ram:IBANID&gt;<i>DE02120300000000202051</i>&lt;/ram:IBANID&gt;<br>
      &lt;ram:GrandTotalAmount&gt;<i>119.00</i>&lt;/ram:GrandTotalAmount&gt;
    </div>
    <div class="ab-pdf"><span class="ab-tag">PDF</span>
      <div class="t">Rechnung RE-0001-2026</div>
      <div class="bar" style="width:75%"></div><div class="bar" style="width:55%"></div>
      <div class="sum">119,00 €</div>
    </div>
  </div>
</div>
""")

# ---------- Choose an invoice ----------

choice = st.radio("Choose an invoice", [*SAMPLES, UPLOAD], horizontal=True)

pdf_bytes = None
file_name = None
if choice == UPLOAD:
    uploaded = st.file_uploader("Drop a ZUGFeRD invoice here", type=["pdf"])
    if uploaded is not None:
        pdf_bytes = uploaded.getvalue()
        file_name = uploaded.name
else:
    path, about = SAMPLES[choice]
    if path.exists():
        pdf_bytes = path.read_bytes()
        file_name = path.name
        st.caption(about)
    else:
        st.warning(f"{path.name} is missing. Save it into the samples folder to use this sample.")

if pdf_bytes is None:
    st.html('<div class="ab-empty">No invoice yet. Upload a ZUGFeRD PDF above, or pick one of the samples.</div>')
    st.stop()

# ---------- Check it ----------

try:
    report = check_invoice(pdf_bytes)
except Exception as error:
    st.error(f"This file could not be read as a PDF: {error}")
    st.stop()

verdict = report["verdict"]
rows = report["rows"]
problems = report["problems"]
not_on_page = [row[0] for row in report["unchecked"]]
matches = sum(1 for row in rows if row[3] == "OK")

if verdict == "DO NOT PAY":
    stop = {row[0]: row[3] for row in problems if row[0] in STOP_PAYMENT_FIELDS}
    colour, stamp = "var(--stamp-red)", "Do not pay"
    if len(stop) > 1:
        headline = "The bank account and the amount to pay in the XML don't match the PDF."
    elif stop.get("IBAN") == "INVALID IN XML":
        headline = "The bank account in the XML is not a valid IBAN."
    elif "IBAN" in stop:
        headline = "The bank account in the XML is not the one on the PDF."
    else:
        headline = "The amount to pay in the XML is not the one on the PDF."
    detail = ("Payment software can take the bank details and the amount from the XML, so the money could go "
              "to the wrong place. Before you pay, call the supplier on a number you already know, "
              "not one from this invoice.")
    others = len(problems) - len(stop)
    if others == 1:
        detail += " 1 more detail also needs fixing."
    elif others > 1:
        detail += f" {others} more details also need fixing."
elif verdict == "FIX FIRST":
    count = len(problems)
    colour, stamp = "var(--stamp-red)", "Fix first"
    headline = (f"{count} detail needs fixing before you book this invoice." if count == 1
                else f"{count} details need fixing before you book this invoice.")
    detail = "The XML is what counts for input VAT. Send the supplier the email below and ask for a corrected invoice."
elif verdict == "SAFE TO BOOK":
    colour, stamp = "var(--ledger)", "Safe to book"
    headline = "The XML and the PDF agree."
    detail = f"All {matches} details found in both layers match, and nothing the tax rules require is missing."
else:
    colour, stamp = "var(--amber)", "No XML found"
    headline = "This PDF has no XML inside."
    detail = "It is an ordinary PDF, not an electronic invoice. Ask the supplier for a ZUGFeRD or XRechnung version."

cautions = []
if "IBAN" in not_on_page:
    cautions.append("The bank account in the XML is not printed on the PDF. Confirm it with the supplier before you pay.")
other_missing = [field for field in not_on_page if field != "IBAN"]
if other_missing:
    cautions.append("Not found on the PDF, so not compared: " + ", ".join(other_missing) + ".")
caution_html = "".join(f'<span class="ab-caution">{escape(text)}</span>' for text in cautions)

st.html(f"""
<div class="ab-result">
  <div class="ab-stamp" style="--c: {colour}">{stamp}</div>
  <div class="ab-result-text"><strong>{escape(headline)}</strong><span>{escape(detail)}</span>
  {caution_html}<span class="ab-note">Checked: {escape(file_name)}</span></div>
</div>
""")

# ---------- Field by field comparison ----------

STATUS = {
    "OK": ("✓ Matches", "ab-ok"),
    "MISMATCH": ("✕ Differs", "ab-bad"),
    "MISSING IN XML": ("✕ Missing in XML", "ab-bad"),
    "INVALID IN XML": ("✕ Not a valid IBAN", "ab-bad"),
    "NOT FOUND ON PAGE": ("? Not found on page", "ab-warn"),
    "not in XML": ("– Not in XML (optional)", "ab-note"),
}


def comparison_table(table_rows, xml_heading):
    lines = []
    for field, xml_value, pdf_value, status in table_rows:
        text, css = STATUS.get(status, (status, ""))
        row_class = "bad" if css == "ab-bad" else ""
        if xml_value == "-":
            xml_cell = "–"
        elif field == "IBAN":   # keep each IBAN on one line
            xml_cell = "<br>".join(f'<code class="ab-iban">{escape(v)}</code>' for v in xml_value.split(", "))
        else:
            xml_cell = f"<code>{escape(str(xml_value))}</code>"
        if pdf_value == "-":
            pdf_cell = "–"
        elif field == "IBAN" and pdf_value != "none shown":
            pdf_cell = "<br>".join(f'<span class="ab-iban">{escape(v)}</span>' for v in pdf_value.split(", "))
        else:
            pdf_cell = escape(str(pdf_value))
        lines.append(
            f'<tr class="{row_class}"><td>{escape(field)}<span class="de">{escape(GERMAN[field])}</span></td>'
            f'<td data-label="XML"><span class="ab-val">{xml_cell}</span></td>'
            f'<td data-label="PDF"><span class="ab-val">{pdf_cell}</span></td>'
            f'<td class="ab-status {css}">{text}</td></tr>'
        )
    return (
        '<div class="ab-wrap"><table class="ab-table"><thead><tr>'
        f"<th>Field</th><th>{xml_heading}</th><th>PDF (what people see)</th><th>Result</th>"
        "</tr></thead><tbody>" + "".join(lines) + "</tbody></table></div>"
    )


tax_rows = [row for row in rows if row[0] not in PAYMENT_FIELDS]
payment_rows = [row for row in rows if row[0] in PAYMENT_FIELDS]

if tax_rows:
    st.html('<h3 class="ab-h">Tax details</h3>'
            '<p class="ab-sub">These decide whether you can claim the input VAT.</p>'
            + comparison_table(tax_rows, "XML (counts for tax)"))
if payment_rows:
    st.html('<h3 class="ab-h">Payment details</h3>'
            '<p class="ab-sub">Banking and accounting software often fills in the payment from the XML.</p>'
            + comparison_table(payment_rows, "XML (used for payment)"))

# ---------- Email to the supplier ----------

email = draft_supplier_email(report)
if email:
    st.html('<h3 class="ab-h">Email to the supplier</h3>'
            '<p class="ab-sub">Written in German and ready to send. Copy it with the button in the corner of the box.</p>')
    if verdict == "DO NOT PAY":
        st.html('<div class="ab-alert">If someone changed this invoice, a reply could reach them instead of your '
                "supplier. Confirm the bank details by phone first, then send this email.</div>")
    st.code(email, language=None, wrap_lines=True)

# ---------- Background ----------

with st.expander("Why this matters"):
    st.write(
        "From 2027, German firms with more than €800,000 turnover must send electronic B2B invoices, "
        "and from 2028 all firms must. The finance ministry's letter of 15 October 2025 says that for "
        "hybrid formats like ZUGFeRD, the XML is what counts. If a required detail is wrong or missing "
        "in the XML, input VAT can be refused, even when the PDF looks correct."
    )
    st.write(
        "Payment is the second risk. Some banking and accounting software fills in the bank account and "
        "the amount from the XML. If someone changes the IBAN inside the XML, the PDF still looks right "
        "but the money goes somewhere else. That is why receivers are advised to check that both layers "
        "match before they pay."
    )

st.html(f"""
<div class="ab-foot">Prototype by Prajwal Shet. Not tax advice. Files are checked in memory and not stored.
<a href="{REPO}" target="_blank">Source code on GitHub</a></div>
""")
