# Abgleich: the checking engine.
# Reads both layers of a ZUGFeRD invoice (hidden XML and visible PDF text),
# compares the tax details and the payment details (bank account, amount, due date, Skonto),
# gives a verdict and drafts a German email to the supplier.

import io
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

import pdfplumber
from facturx import get_xml_from_pdf

NS = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
}

XML_PATHS = {
    "Invoice number": "rsm:ExchangedDocument/ram:ID",
    "Invoice type": "rsm:ExchangedDocument/ram:TypeCode",
    "Invoice date": "rsm:ExchangedDocument/ram:IssueDateTime/udt:DateTimeString",
    "Seller": ".//ram:SellerTradeParty/ram:Name",
    "Seller VAT ID": ".//ram:SellerTradeParty/ram:SpecifiedTaxRegistration/ram:ID[@schemeID='VA']",
    "Buyer": ".//ram:BuyerTradeParty/ram:Name",
    "Net amount": ".//ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:TaxBasisTotalAmount",
    "VAT rate %": ".//ram:ApplicableHeaderTradeSettlement/ram:ApplicableTradeTax/ram:RateApplicablePercent",
    "VAT amount": ".//ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:TaxTotalAmount",
    "Total": ".//ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:GrandTotalAmount",
    "Amount due": ".//ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:DuePayableAmount",
    "Due date": ".//ram:SpecifiedTradePaymentTerms/ram:DueDateDateTime/udt:DateTimeString",
}

# The supplier's bank account (where the money goes) and the payment terms
IBAN_PATH = ".//ram:SpecifiedTradeSettlementPaymentMeans/ram:PayeePartyCreditorFinancialAccount/ram:IBANID"
TERMS_PATH = ".//ram:SpecifiedTradePaymentTerms/ram:Description"
DISCOUNT_PERCENT_PATH = ".//ram:ApplicableTradePaymentDiscountTerms/ram:CalculationPercent"
DISCOUNT_DAYS_PATH = ".//ram:ApplicableTradePaymentDiscountTerms/ram:BasisPeriodMeasure"

# The order of the rows in the report, in two groups
TAX_FIELDS = ["Invoice number", "Invoice type", "Invoice date", "Seller", "Seller VAT ID", "Buyer",
              "Net amount", "VAT rate %", "VAT amount", "Total"]
PAYMENT_FIELDS = ["Amount due", "Due date", "Early payment discount", "IBAN"]

# Details the XML must contain before input VAT can safely be claimed
REQUIRED = ["Invoice number", "Invoice type", "Invoice date", "Seller", "Seller VAT ID", "Buyer",
            "Net amount", "VAT rate %", "VAT amount", "Total"]

# If one of these is wrong, money could go to the wrong account or the wrong amount could be paid
STOP_PAYMENT_FIELDS = ["IBAN", "Amount due"]

# German names used in the supplier email
GERMAN = {
    "Invoice number": "Rechnungsnummer",
    "Invoice type": "Rechnungsart",
    "Invoice date": "Rechnungsdatum",
    "Seller": "Name des Rechnungsstellers",
    "Seller VAT ID": "USt-IdNr. des Rechnungsstellers",
    "Buyer": "Name des Rechnungsempfängers",
    "Net amount": "Nettobetrag",
    "VAT rate %": "Steuersatz",
    "VAT amount": "Umsatzsteuerbetrag",
    "Total": "Gesamtbetrag",
    "Amount due": "Zahlbetrag",
    "Due date": "Fälligkeitsdatum",
    "Early payment discount": "Skonto",
    "IBAN": "IBAN (Bankverbindung)",
}

# Invoice type codes used on German e-invoices: code -> (English name, German name, kind)
TYPE_CODES = {
    "380": ("invoice", "Rechnung", "invoice"),
    "326": ("partial invoice", "Teilrechnung", "invoice"),
    "386": ("prepayment invoice", "Anzahlungsrechnung", "invoice"),
    "875": ("partial construction invoice", "Abschlagsrechnung", "invoice"),
    "876": ("partial final construction invoice", "Teilschlussrechnung", "invoice"),
    "877": ("final construction invoice", "Schlussrechnung", "invoice"),
    "381": ("credit note", "Gutschrift", "credit"),
    "261": ("self-billed credit note", "Gutschrift", "credit"),
    "384": ("corrected invoice", "Rechnungskorrektur", "corrected"),
    "389": ("self-billed invoice", "Gutschrift", "self-billed"),
}

# What the visible page calls itself
PAGE_KINDS = {
    "invoice": ("invoice", "Rechnung"),
    "credit": ("credit note (Gutschrift)", "Gutschrift"),
    "corrected": ("corrected invoice", "Rechnungskorrektur"),
}

# Length of an IBAN in common European countries
IBAN_LENGTHS = {"DE": 22, "AT": 20, "CH": 21, "LI": 21, "NL": 18, "BE": 16, "LU": 20, "FR": 27,
                "IT": 27, "ES": 24, "PT": 25, "PL": 28, "CZ": 24, "DK": 18, "SE": 24, "FI": 18,
                "NO": 15, "IE": 22, "GB": 22}

AMOUNT = r"(-?€?\s?[\d.,]+\s?€?)"
MONEY = r"(-?€?\s?\d+(?:[.,]\d{3})*[.,]\d{2}(?!\d|[.,]\d)\s?€?)"   # an amount with cents, never a date
DATE = r"([A-Z][a-z]+ \d{1,2}, \d{4}|\d{1,2}\.\d{1,2}\.\d{2,4})"
PERCENT = r"(\d{1,2}(?:[.,]\d{1,2})?)\s?%"
DAYS = r"(\d{1,3})\s*(?:Tagen|Tage|days)"

# What to look for on the visible page (English and German labels)
TEXT_PATTERNS = {
    "Invoice number": r"(?:Invoice No\.?|Invoice number|Rechnungsnummer|Rechnungs-Nr\.?|Rechnung Nr\.?)[:\s]*([A-Z0-9][\w\-/]*)",
    "Invoice date": r"(?:Invoice date|Rechnungsdatum)[:\s]*" + DATE,
    "Due date": r"(?:Due on|Due date|Fällig am|Zahlbar bis)[:\s]*" + DATE,
    "Net amount": r"(?:Total Net|Net amount|Nettobetrag|Summe netto|Gesamt netto)[:\s]*" + AMOUNT,
    "VAT rate %": r"(\d{1,2}(?:[.,]\d+)?)\s?%\s?(?:VAT|USt|MwSt)",
    "VAT amount": r"\d{1,2}(?:[.,]\d+)?\s?%\s?(?:VAT|USt|MwSt)\.?[^\n€\d]*" + AMOUNT,
    "Total": r"(?:Total amount|Gross amount|Gesamtbetrag|Rechnungsbetrag|Bruttobetrag)[:\s]*" + AMOUNT,
    "Amount due": r"(?:Amount due|Balance due|Total due|Zahlbetrag|Zu zahlender Betrag|Offener Betrag|Restbetrag)[:\s]*" + MONEY,
}


# ---------- Reading the two layers ----------

def read_xml_fields(pdf_bytes):
    xml_name, xml_bytes = get_xml_from_pdf(pdf_bytes, check_xsd=False)
    if not xml_bytes:
        return None
    root = ET.fromstring(xml_bytes)
    fields = {}
    for label, path in XML_PATHS.items():
        element = root.find(path, NS)
        fields[label] = element.text.strip() if element is not None and element.text else None
    fields["IBAN"] = [clean_iban(e.text) for e in root.findall(IBAN_PATH, NS) if e.text and e.text.strip()]
    fields["Early payment discount"] = read_xml_discount(root)
    return fields


def read_pdf_text(pdf_bytes):
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


# ---------- Turning text into comparable values ----------

def to_amount(text):
    """Turn '€1,234.56', '1.234,56 €' or '119.00' into Decimal('1234.56')."""
    if text is None:
        return None
    cleaned = re.sub(r"[^\d.,\-]", "", text)
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):      # German style 1.234,56
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:                                            # English style 1,234.56
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:                                 # 119,00
        cleaned = cleaned.replace(",", ".")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def to_date(text):
    """Turn 'October 11, 2026', '11.10.2026' or '20261011' into '20261011'."""
    if text is None:
        return None
    text = text.strip()
    for fmt in ("%Y%m%d", "%B %d, %Y", "%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y%m%d")
        except ValueError:
            pass
    return None


def german_date(text):
    """Turn '20261011' into '11.10.2026' for the email."""
    normal = to_date(text)
    return f"{normal[6:8]}.{normal[4:6]}.{normal[0:4]}" if normal else text


def squash(text):
    """Lower case and single spaces, so line breaks don't cause false alarms."""
    return re.sub(r"\s+", " ", text).strip().lower()


def read_text_values(text):
    values = {}
    for label, pattern in TEXT_PATTERNS.items():
        match = re.search(pattern, text, re.IGNORECASE)
        values[label] = match.group(1).strip() if match else None
    return values


# ---------- Bank account (IBAN) ----------

def clean_iban(text):
    return re.sub(r"\s+", "", text).upper()


def nice_iban(iban):
    """Show an IBAN in groups of four, the way it is printed on invoices."""
    return " ".join(iban[i:i + 4] for i in range(0, len(iban), 4))


def iban_is_valid(iban):
    """Check the two check digits of an IBAN (the standard mod 97 test)."""
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", iban):
        return False
    if iban[:2] in IBAN_LENGTHS and len(iban) != IBAN_LENGTHS[iban[:2]]:
        return False
    moved = iban[4:] + iban[:4]
    return int("".join(str(int(ch, 36)) for ch in moved)) % 97 == 1


def find_ibans_on_page(text):
    found = []
    for match in re.finditer(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?\b", text):
        raw = clean_iban(match.group(0))
        length = IBAN_LENGTHS.get(raw[:2])
        if length:
            iban = raw[:length] if len(raw) >= length else None
        else:
            iban = next((raw[:n] for n in range(len(raw), 14, -1) if iban_is_valid(raw[:n])), None)
        if iban and iban not in found:
            found.append(iban)
    return found


# ---------- Early payment discount (Skonto) ----------

def is_discount_line(line, both):
    """True for early payment terms, not for a normal price discount on an item."""
    if re.search(r"skonto|cash discount|early payment discount|prompt payment discount", line, re.IGNORECASE):
        return True
    return bool(re.search(r"discount", line, re.IGNORECASE)
                and re.search(r"\bdays?\b|\bpaid\b|\bpayment\b", both, re.IGNORECASE))


def nearest(pattern, text, position, flags=0):
    """The match of pattern in text that is closest to position, or None."""
    matches = list(re.finditer(pattern, text, flags))
    return min(matches, key=lambda m: abs(m.start() - position)) if matches else None


def discount_clause(line):
    """The part of a line that mentions Skonto, so '30 Tage netto, 2 % Skonto in 10 Tagen' gives the second part."""
    for part in re.split(r"[;,]\s+|\.\s+", line):
        if re.search(r"skonto|discount", part, re.IGNORECASE):
            return part
    return line


def read_discount(text):
    """Find terms like '2 % Skonto innerhalb von 10 Tagen'. Returns (percent, days, date) or None."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        both = line + " " + (lines[i + 1] if i + 1 < len(lines) else "")
        if not is_discount_line(line, both):
            continue
        # Look in the Skonto part of the line first, then the whole line, then the next line too
        for scope in (discount_clause(line), line, both):
            percent = re.search(PERCENT, scope)
            if not percent:
                continue
            word = re.search(r"skonto|discount", scope, re.IGNORECASE)
            anchor = word.start() if word else percent.start()
            days = nearest(DAYS, scope, anchor, re.IGNORECASE)
            date = None if days else nearest(DATE, scope, anchor)
            if days or date or scope is both:
                return (to_amount(percent.group(1)), int(days.group(1)) if days else None,
                        to_date(date.group(1)) if date else None)
    return None


def read_xml_discount(root):
    for element in root.findall(TERMS_PATH, NS):
        text = element.text or ""
        coded = re.search(r"#SKONTO#TAGE=(\d+)#PROZENT=(\d+(?:\.\d+)?)", text, re.IGNORECASE)
        if coded:
            return (Decimal(coded.group(2)), int(coded.group(1)), None)
        written = read_discount(text)
        if written:
            return written
    percent = root.find(DISCOUNT_PERCENT_PATH, NS)
    if percent is not None and percent.text:
        days = root.find(DISCOUNT_DAYS_PATH, NS)
        days = int(Decimal(days.text.strip())) if days is not None and days.text else None
        return (Decimal(percent.text.strip()), days, None)
    return None


def discount_text(discount):
    percent, days, date = discount
    shown = f"{percent.normalize():f}%"
    if days:
        return f"{shown} within {days} days"
    if date:
        return f"{shown} if paid by {german_date(date)}"
    return shown


def same_discount(xml_d, page_d, invoice_date):
    if xml_d[0] != page_d[0]:
        return False
    if xml_d[1] and page_d[1]:
        return xml_d[1] == page_d[1]
    if xml_d[1] and page_d[2] and to_date(invoice_date):
        deadline = datetime.strptime(to_date(invoice_date), "%Y%m%d") + timedelta(days=xml_d[1])
        return deadline.strftime("%Y%m%d") == page_d[2]
    return True


# ---------- Invoice type ----------

def read_page_kind(text):
    """What does the top of the page call this document: invoice, credit note or correction?"""
    top = squash("\n".join(text.splitlines()[:20]))
    if re.search(r"gutschrift|credit note|credit memo|\bstorno", top):
        return "credit", top
    if re.search(r"rechnungskorrektur|korrekturrechnung|corrected invoice|invoice correction", top):
        return "corrected", top
    if re.search(r"\b(rechnung|invoice)", top):
        return "invoice", top
    return None, top


def check_type(code, text):
    if code is None:
        return ("Invoice type", "-", "-", "MISSING IN XML")
    english, german, kind = TYPE_CODES.get(code, ("other", "Sonstige", "invoice"))
    page_kind, top = read_page_kind(text)
    xml_value = f"{code} ({english})"
    if page_kind is None:
        return ("Invoice type", xml_value, "-", "NOT FOUND ON PAGE")
    if kind == "self-billed":
        same = "gutschrift" in top or "self-billed" in top or "self billing" in top
    else:
        same = kind == page_kind
    return ("Invoice type", xml_value, PAGE_KINDS[page_kind][0], "OK" if same else "MISMATCH")


# ---------- Comparing ----------

def compare(xml, text, text_values):
    rows = []  # (field, xml value, pdf value, status)
    page = squash(text)

    for label in TAX_FIELDS + PAYMENT_FIELDS:

        if label == "Invoice type":
            rows.append(check_type(xml.get(label), text))
            continue

        if label == "IBAN":
            xml_ibans = xml.get("IBAN") or []
            page_ibans = find_ibans_on_page(text)
            compact = re.sub(r"\s+", "", text).upper()
            for iban in xml_ibans:   # also catches an IBAN that is split over two lines on the page
                if iban not in page_ibans and iban in compact:
                    page_ibans.append(iban)
            pdf_value = ", ".join(nice_iban(i) for i in page_ibans) or "none shown"
            if not xml_ibans:
                rows.append((label, "-", pdf_value, "not in XML"))
                continue
            xml_value = ", ".join(nice_iban(i) for i in xml_ibans)
            if not all(iban_is_valid(i) for i in xml_ibans):
                status = "INVALID IN XML"
            elif not page_ibans:
                status = "NOT FOUND ON PAGE"
            else:
                status = "OK" if all(i in page_ibans for i in xml_ibans) else "MISMATCH"
            rows.append((label, xml_value, pdf_value, status))
            continue

        if label == "Early payment discount":
            xml_d = xml.get(label)
            page_d = read_discount(text)
            if xml_d and page_d:
                same = same_discount(xml_d, page_d, xml.get("Invoice date"))
                rows.append((label, discount_text(xml_d), discount_text(page_d), "OK" if same else "MISMATCH"))
            elif xml_d:
                rows.append((label, discount_text(xml_d), "-", "NOT FOUND ON PAGE"))
            elif page_d:
                rows.append((label, "-", discount_text(page_d), "MISSING IN XML"))
            continue

        xml_value = xml.get(label)

        if xml_value is None:
            status = "MISSING IN XML" if label in REQUIRED else "not in XML"
            rows.append((label, "-", "-", status))
            continue

        # Names and IDs: the XML value should appear somewhere on the page
        if label in ("Seller", "Buyer", "Seller VAT ID"):
            found = squash(xml_value) in page
            rows.append((label, xml_value, "found on page" if found else "not on page",
                         "OK" if found else "MISMATCH"))
            continue

        pdf_raw = text_values.get(label)
        if label == "Amount due" and pdf_raw is None and text_values.get("Total"):
            pdf_raw = text_values["Total"] + " (total)"   # no separate amount due, so use the total
        if pdf_raw is None:
            rows.append((label, xml_value, "-", "NOT FOUND ON PAGE"))
            continue

        if label in ("Invoice date", "Due date"):
            same = to_date(xml_value) == to_date(pdf_raw)
        elif label == "Invoice number":
            same = xml_value.strip() == pdf_raw.strip()
        else:
            same = to_amount(xml_value) == to_amount(pdf_raw.replace(" (total)", ""))

        rows.append((label, xml_value, pdf_raw, "OK" if same else "MISMATCH"))
    return rows


def check_invoice(pdf_bytes):
    """Main entry point: returns a report dictionary for one invoice."""
    xml = read_xml_fields(pdf_bytes)
    if xml is None:
        return {"verdict": "NOT AN E-INVOICE", "rows": [], "problems": [],
                "unchecked": [], "xml": None}

    text = read_pdf_text(pdf_bytes)
    rows = compare(xml, text, read_text_values(text))
    problems = [r for r in rows if r[3] in ("MISMATCH", "MISSING IN XML", "INVALID IN XML")]
    unchecked = [r for r in rows if r[3] == "NOT FOUND ON PAGE"]
    if any(r[0] in STOP_PAYMENT_FIELDS for r in problems):
        verdict = "DO NOT PAY"
    elif problems:
        verdict = "FIX FIRST"
    else:
        verdict = "SAFE TO BOOK"
    return {"verdict": verdict, "rows": rows, "problems": problems,
            "unchecked": unchecked, "xml": xml}


# ---------- Drafting the supplier email ----------

def in_german(field, value):
    """Translate a value from the report into German for the email."""
    if field in ("Invoice date", "Due date"):
        return german_date(value)
    if field == "Invoice type":
        code = value.split()[0]
        if code in TYPE_CODES:
            return f"{code} ({TYPE_CODES[code][1]})"
        for english, german in PAGE_KINDS.values():
            if value == english:
                return german
    if field == "Early payment discount":
        return (value.replace("% within ", " % innerhalb von ").replace(" days", " Tagen")
                .replace("% if paid by ", " % bei Zahlung bis "))
    if field == "Amount due":
        return value.replace(" (total)", " (Gesamtbetrag)")
    if value == "none shown":
        return "nicht angegeben"
    return value


def draft_supplier_email(report):
    """Return a German email asking for a corrected invoice, or None if not needed."""
    if report["verdict"] == "SAFE TO BOOK":
        return None

    if report["verdict"] == "NOT AN E-INVOICE":
        return (
            "Betreff: Bitte um Rechnung im elektronischen Format\n\n"
            "Sehr geehrte Damen und Herren,\n\n"
            "vielen Dank für Ihre Rechnung. Leider enthält die Datei keinen strukturierten "
            "Datensatz (ZUGFeRD oder XRechnung).\n\n"
            "Bitte senden Sie uns die Rechnung als elektronische Rechnung nach EN 16931.\n\n"
            "Vielen Dank und freundliche Grüße"
        )

    xml = report["xml"]
    number = xml.get("Invoice number") or "(ohne Nummer)"
    date = german_date(xml.get("Invoice date")) if xml.get("Invoice date") else "(ohne Datum)"

    lines = []
    for field, xml_value, pdf_value, status in report["problems"]:
        name = GERMAN[field]
        if status == "MISSING IN XML" and pdf_value not in ("-", None):
            lines.append(f'- {name}: in der sichtbaren Rechnung (PDF) "{in_german(field, pdf_value)}", '
                         "im strukturierten Datensatz (XML) fehlt diese Angabe")
        elif status == "MISSING IN XML":
            lines.append(f"- {name}: fehlt im strukturierten Datensatz (XML)")
        elif status == "INVALID IN XML":
            lines.append(f'- {name}: die im XML angegebene IBAN "{xml_value}" ist ungültig')
        elif pdf_value in ("found on page", "not on page"):
            lines.append(f'- {name}: im XML "{xml_value}", in der sichtbaren Rechnung (PDF) nicht enthalten')
        else:
            lines.append(f'- {name}: im XML "{in_german(field, xml_value)}", '
                         f'in der sichtbaren Rechnung (PDF) "{in_german(field, pdf_value)}"')

    if report["verdict"] == "DO NOT PAY":
        problem_fields = [r[0] for r in report["problems"]]
        confirm = []
        if "IBAN" in problem_fields:
            confirm.append("Ihre Bankverbindung")
        if "Amount due" in problem_fields:
            confirm.append("den Zahlbetrag")
        return (
            f"Betreff: Rückfrage zu Ihrer Rechnung {number}: Zahlungsangaben bitte bestätigen\n\n"
            "Sehr geehrte Damen und Herren,\n\n"
            f"vielen Dank für Ihre Rechnung {number} vom {date}.\n\n"
            "Bei der Prüfung ist uns aufgefallen, dass die Angaben im strukturierten Datensatz (XML) "
            "Ihrer elektronischen Rechnung nicht mit der sichtbaren Rechnung (PDF) übereinstimmen:\n\n"
            + "\n".join(lines) + "\n\n"
            f"Bitte bestätigen Sie uns {' und '.join(confirm)} und senden Sie uns eine "
            "korrigierte Rechnung. Bis zur Klärung halten wir die Zahlung zurück.\n\n"
            "Vielen Dank und freundliche Grüße"
        )

    return (
        f"Betreff: Bitte um Korrektur der Rechnung {number}\n\n"
        "Sehr geehrte Damen und Herren,\n\n"
        f"vielen Dank für Ihre Rechnung {number} vom {date}.\n\n"
        "Bei der Prüfung ist uns aufgefallen, dass der strukturierte Datensatz (XML) Ihrer "
        "elektronischen Rechnung nicht mit der sichtbaren Rechnung (PDF) übereinstimmt "
        "oder Pflichtangaben fehlen:\n\n"
        + "\n".join(lines) + "\n\n"
        "Da für den Vorsteuerabzug der strukturierte Datensatz maßgeblich ist, bitten wir Sie "
        "um eine korrigierte Rechnung.\n\n"
        "Vielen Dank und freundliche Grüße"
    )
