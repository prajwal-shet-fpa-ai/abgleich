# Check one invoice from the terminal.
# Run:  python compare.py                         (checks samples/good_invoice.pdf)
#       python compare.py samples/other_file.pdf   (checks another invoice)

import sys
from checker import check_invoice, draft_supplier_email

PDF_PATH = sys.argv[1] if len(sys.argv) > 1 else "samples/good_invoice.pdf"

with open(PDF_PATH, "rb") as pdf_file:
    report = check_invoice(pdf_file.read())

print(f"Checking: {PDF_PATH}\n")

if report["rows"]:
    print(f"{'FIELD':<16}{'XML (counts for tax)':<26}{'PDF (what people see)':<26}STATUS")
    print("-" * 82)
    for field, xml_value, pdf_value, status in report["rows"]:
        print(f"{field:<16}{str(xml_value):<26}{str(pdf_value):<26}{status}")
    print()

print(f"VERDICT: {report['verdict']}")
for field, xml_value, pdf_value, status in report["problems"]:
    print(f"  - {field}: {status}")

if report["unchecked"]:
    print("\nCould not find these on the page, so they were not compared:")
    for field, *_ in report["unchecked"]:
        print(f"  - {field}")

email = draft_supplier_email(report)
if email:
    print("\n========== EMAIL TO SUPPLIER (copy and send) ==========\n")
    print(email)