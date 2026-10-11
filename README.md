# Abgleich: is this electronic invoice safe to book and safe to pay?

**Live demo:** coming soon

Abgleich checks German ZUGFeRD invoices. A ZUGFeRD invoice is a PDF with a hidden XML file inside. People read the PDF, while accounting and banking software read the XML. Abgleich reads both layers, compares them field by field and tells you whether the invoice is safe to book and safe to pay. If something is wrong, it writes the email to the supplier in German.

## Why this matters

- From January 2027, German companies with more than €800,000 turnover must send B2B invoices as electronic invoices. From January 2028, all companies must.
- For hybrid formats like ZUGFeRD, the German finance ministry (BMF) says the XML is what counts for tax. If a required detail is wrong or missing in the XML, the input VAT deduction can be refused, even when the PDF looks correct.
- The two layers are not forced to match. Someone can change the bank account (IBAN) inside the XML while the PDF still shows the real one. Some banking software fills in the payment from the XML, so the money could go to the wrong account.

## A real example

I made an invoice on a free German invoicing website. The XML named the buyer "Beispiel Handel GmbH" but the PDF showed "Example Trading GmbH". The PDF looked fine to a person. Abgleich flagged the difference and wrote the correction request to the supplier.

## What it checks

| Group | Fields |
|---|---|
| Tax details | Invoice number, invoice type (invoice, credit note, corrected invoice), invoice date, seller name, seller VAT ID, buyer name, net amount, VAT rate, VAT amount, total |
| Payment details | Amount due, due date, early payment discount (Skonto), IBAN |

The IBAN in the XML is compared with the one printed on the PDF, and its check digits are tested.

## Verdicts

| Verdict | Meaning |
|---|---|
| DO NOT PAY | The bank account or the amount to pay in the XML differs from the PDF, or the IBAN is not valid. Confirm the bank details with the supplier by phone before paying. |
| FIX FIRST | A tax detail differs between the layers or is missing in the XML. Ask the supplier for a corrected invoice. |
| SAFE TO BOOK | Everything found in both layers matches and nothing required is missing. |
| NO XML FOUND | The PDF has no XML inside, so it is not an electronic invoice. |

## How it works

1. **factur-x** takes the XML out of the PDF.
2. **pdfplumber** reads the visible text of the PDF.
3. **checker.py** finds each value in both layers (English and German labels, German and English number and date formats) and compares them.
4. **Streamlit** shows the result as a web page. Files are checked in memory and not stored.

## Files

| File | What it is |
|---|---|
| app.py | The web page |
| checker.py | The checking engine |
| compare.py | Runs a check in the terminal |
| samples/good_invoice.pdf | The real example invoice |
| samples/fraud_example.pdf | A test invoice where the IBAN inside the XML was changed |

## Run it yourself

```
git clone https://github.com/prajwal-shet-fpa-ai/abgleich.git
cd abgleich
pip install -r requirements.txt
python -m streamlit run app.py
```

To check one file in the terminal:

```
python compare.py samples/fraud_example.pdf
```

## Limits

- Works with ZUGFeRD and Factur-X (a PDF with XML inside). XRechnung files, which are XML only, are not supported yet.
- Checks the main invoice details, not line items, addresses or the delivery date.
- Handles one VAT rate per invoice.
- Reads the visible text with patterns. On an unusual layout a value may show as "Not found on page" instead of being compared.
- Does not test the XML against the full EN 16931 rules. The KoSIT validator does that.
- This is a prototype, not tax advice.

## Next steps

- XRechnung support
- Delivery date and address checks
- Several VAT rates and line items
- Checking many invoices at once

Built by Prajwal Shet with Python 3.13.