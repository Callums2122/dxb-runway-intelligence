from pathlib import Path

from dxb_runway.reporting import create_financial_pdf


def test_professional_pdf_export(tmp_path: Path):
    destination=tmp_path/"report.pdf"
    create_financial_pdf(destination,month="July 2026",summary={"Income":"AED 6,000","Expenditure":"AED 4,970","Net cash flow":"AED 1,030","Commission pending":"AED 0"},rows=[{"occurred_at":"2026-07-15T12:00:00","kind":"expense","category":"Groceries","merchant":"Carrefour","currency":"AED","amount":310}])
    assert destination.read_bytes().startswith(b"%PDF")
    assert destination.stat().st_size>1000

