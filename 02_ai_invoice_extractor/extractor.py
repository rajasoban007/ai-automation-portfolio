"""
DEMO PROJECT (sample data) - AI invoice / PO data extractor.

Pipeline:  PDF invoices -> field extraction -> validation rules -> auto-approve
           or human-review queue -> CSV + Excel register.

Two interchangeable extraction back-ends:
  * ClaudeExtractor  - sends the PDF to Claude (Anthropic Messages API, official SDK)
                       with a JSON-schema structured output. Needs `pip install anthropic`
                       and the client's own API key (ANTHROPIC_API_KEY).
  * OfflineExtractor - deterministic rule-based parser for the sample layouts, so the
                       demo and the test suite run with no key and no cost.

Usage:
    python extractor.py                       # offline mode on ./samples
    python extractor.py --mode claude         # real LLM extraction (client key required)
"""
from __future__ import annotations

import argparse
import base64
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pymupdf

HERE = Path(__file__).parent
DEFAULT_MODEL = "claude-opus-5-5"

# --------------------------------------------------------------------------- schema
LINE_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "description": {"type": "string"},
        "quantity": {"type": "number"},
        "unit_price": {"type": "number"},
        "amount": {"type": "number"},
    },
    "required": ["description", "quantity", "unit_price", "amount"],
    "additionalProperties": False,
}
INVOICE_SCHEMA = {
    "type": "object",
    "properties": {
        "supplier": {"type": "string"},
        "invoice_number": {"type": "string"},
        "invoice_date": {"type": "string", "description": "ISO 8601 date, YYYY-MM-DD"},
        "po_number": {"type": "string", "description": "Empty string if not present"},
        "currency": {"type": "string", "description": "ISO 4217 code, e.g. USD"},
        "subtotal": {"type": "number"},
        "tax": {"type": "number"},
        "total": {"type": "number"},
        "line_items": {"type": "array", "items": LINE_ITEM_SCHEMA},
    },
    "required": ["supplier", "invoice_number", "invoice_date", "po_number", "currency",
                 "subtotal", "tax", "total", "line_items"],
    "additionalProperties": False,
}

PROMPT = (
    "Extract the invoice fields from the attached supplier invoice. "
    "Copy values exactly as printed; do not correct arithmetic. "
    "Convert the invoice date to YYYY-MM-DD. If there is no purchase order number, "
    "return an empty string for po_number. Amounts are plain numbers without currency "
    "symbols or thousands separators."
)


class ExtractionError(Exception):
    pass


# --------------------------------------------------------------------------- back-ends
class ClaudeExtractor:
    """LLM extraction via the Anthropic Python SDK with structured outputs."""

    def __init__(self, client=None, model: str = DEFAULT_MODEL, effort: str = "low"):
        if client is None:
            try:
                import anthropic  # imported lazily so offline mode needs no SDK
            except ImportError as e:  # pragma: no cover - depends on environment
                raise ExtractionError("pip install anthropic  (required for --mode claude)") from e
            client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY / ant auth profile
        self.client, self.model, self.effort = client, model, effort

    def build_request(self, pdf_bytes: bytes) -> dict:
        return dict(
            model=self.model,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",  # re-run on a fallback model if the request is declined
            output_config={
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": INVOICE_SCHEMA},
            },
            messages=[{
                "role": "user",
                "content": [
                    {"type": "document", "source": {
                        "type": "base64", "media_type": "application/pdf",
                        "data": base64.standard_b64encode(pdf_bytes).decode("ascii")}},
                    {"type": "text", "text": PROMPT},
                ],
            }],
        )

    def extract(self, pdf_path: Path) -> dict:
        response = self.client.beta.messages.create(**self.build_request(pdf_path.read_bytes()))
        if response.stop_reason == "refusal":
            raise ExtractionError(f"{pdf_path.name}: request declined by the model")
        if response.stop_reason == "max_tokens":
            raise ExtractionError(f"{pdf_path.name}: response truncated")
        text = next((b.text for b in response.content if getattr(b, "type", "") == "text"), None)
        if text is None:
            raise ExtractionError(f"{pdf_path.name}: no text block in response")
        data = json.loads(text)
        data["_confidence"] = "model"
        return data


class OfflineExtractor:
    """Rule-based parser for the demo's sample layouts (no API, no cost)."""

    NUM = r"([\d,]+\.\d{2})"
    PATTERNS = {
        "invoice_number": r"^(?:Invoice No:|Inv #|Bill Number:)\s*(\S+)",
        "invoice_date": r"^(?:Invoice Date:|Date:|Bill Date:)\s*(.+)$",
        "po_number": r"^(?:PO Number:|Purchase Order:|Your PO Ref:)\s*(\S+)",
        "subtotal": r"^Subtotal:\s+([A-Z]{3})\s+" + NUM,
        "tax": r"^(?:Sales Tax[^:]*|Tax|GST[^:]*):\s+[A-Z]{3}\s+" + NUM,
        "total": r"^(?:Grand Total|Amount Due|Total Due):\s+[A-Z]{3}\s+" + NUM,
    }
    LINE = re.compile(r"^(.+?)\s{2,}(\d+)\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})$")
    DATE_FORMATS = ("%d/%m/%Y", "%B %d, %Y", "%Y-%m-%d")

    @staticmethod
    def _num(s: str) -> float:
        return float(s.replace(",", ""))

    def extract(self, pdf_path: Path) -> dict:
        with pymupdf.open(pdf_path) as doc:
            lines = [ln.strip() for p in doc for ln in p.get_text().splitlines() if ln.strip()]
        out = {"supplier": lines[0] if lines else "", "po_number": "", "line_items": []}
        for ln in lines:
            for key, pat in self.PATTERNS.items():
                m = re.search(pat, ln)
                if not m:
                    continue
                if key == "subtotal":
                    out["currency"], out["subtotal"] = m.group(1), self._num(m.group(2))
                elif key in ("tax", "total"):
                    out[key] = self._num(m.group(1))
                elif key == "invoice_date":
                    out[key] = self._parse_date(m.group(1))
                else:
                    out[key] = m.group(1)
            m = self.LINE.match(ln)
            if m and not ln.startswith("Description"):
                out["line_items"].append({
                    "description": m.group(1).strip(), "quantity": float(m.group(2)),
                    "unit_price": self._num(m.group(3)), "amount": self._num(m.group(4))})
        out["_confidence"] = "rules"
        return out

    def _parse_date(self, s: str) -> str:
        for fmt in self.DATE_FORMATS:
            try:
                return datetime.strptime(s.strip(), fmt).date().isoformat()
            except ValueError:
                continue
        return ""


# --------------------------------------------------------------------------- validation
VENDOR_MASTER = {
    "Lahore Paper House (Sample)", "ColorTech Supplies (Sample)", "BindRight Traders (Sample)",
    "PlateMakers Co. (Sample)", "PackLine Cartons (Sample)",
}
TOL = 0.011


@dataclass
class Result:
    file: str
    data: dict
    issues: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "NEEDS REVIEW" if self.issues else "AUTO-APPROVED"


def validate(results: list[Result], vendor_master=VENDOR_MASTER, today: date | None = None,
             seen: set | None = None) -> list[Result]:
    today = today or date.today()
    seen = set() if seen is None else seen
    for r in results:
        d = r.data
        for f in ("supplier", "invoice_number", "invoice_date", "total"):
            if d.get(f) in (None, ""):
                r.issues.append(f"missing {f}")
        if d.get("supplier") and d["supplier"] not in vendor_master:
            r.issues.append("supplier not in vendor master")
        if not d.get("po_number"):
            r.issues.append("no PO number - cannot 3-way match")
        items = d.get("line_items") or []
        if not items:
            r.issues.append("no line items found")
        for it in items:
            if abs(it["quantity"] * it["unit_price"] - it["amount"]) > TOL:
                r.issues.append(f"line '{it['description']}': qty x price != amount")
        if items and d.get("subtotal") is not None and abs(sum(i["amount"] for i in items) - d["subtotal"]) > TOL:
            r.issues.append("line items do not sum to subtotal")
        if None not in (d.get("subtotal"), d.get("tax"), d.get("total")):
            expected = round(d["subtotal"] + d["tax"], 2)
            if abs(expected - d["total"]) > TOL:
                r.issues.append(f"total {d['total']:,.2f} != subtotal + tax {expected:,.2f}")
        if d.get("invoice_date"):
            inv_date = date.fromisoformat(d["invoice_date"])
            if inv_date > today:
                r.issues.append("invoice dated in the future")
            elif (today - inv_date).days > 90:
                r.issues.append("invoice older than 90 days")
        key = (d.get("supplier"), d.get("invoice_number"))
        if all(key):
            if key in seen:
                r.issues.append("DUPLICATE: same supplier + invoice number already processed")
            seen.add(key)
    return results


# --------------------------------------------------------------------------- outputs
def write_outputs(results: list[Result], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(exist_ok=True)
    inv_rows, line_rows = [], []
    for r in results:
        d = r.data
        inv_rows.append({
            "file": r.file, "status": r.status, "issues": "; ".join(r.issues),
            "supplier": d.get("supplier"), "invoice_number": d.get("invoice_number"),
            "invoice_date": d.get("invoice_date"), "po_number": d.get("po_number"),
            "currency": d.get("currency"), "subtotal": d.get("subtotal"), "tax": d.get("tax"),
            "total": d.get("total"), "extracted_by": d.get("_confidence")})
        for it in d.get("line_items") or []:
            line_rows.append({"file": r.file, "invoice_number": d.get("invoice_number"), **it})
    inv, lines = pd.DataFrame(inv_rows), pd.DataFrame(line_rows)
    review = inv[inv.status == "NEEDS REVIEW"]
    paths = {
        "invoices": out_dir / "invoices.csv", "line_items": out_dir / "line_items.csv",
        "review_queue": out_dir / "review_queue.csv", "register": out_dir / "invoice_register.xlsx"}
    inv.to_csv(paths["invoices"], index=False)
    lines.to_csv(paths["line_items"], index=False)
    review.to_csv(paths["review_queue"], index=False)
    with pd.ExcelWriter(paths["register"], engine="openpyxl") as xw:
        inv.to_excel(xw, sheet_name="Invoices", index=False)
        review.to_excel(xw, sheet_name="Review Queue", index=False)
        lines.to_excel(xw, sheet_name="Line Items", index=False)
        for ws in xw.book.worksheets:
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = min(
                    60, max(len(str(c.value or "")) for c in col) + 2)
            ws.freeze_panes = "A2"
    return paths


def run(input_dir: Path, extractor, out_dir: Path) -> list[Result]:
    results = []
    for pdf in sorted(input_dir.glob("*.pdf")):
        try:
            results.append(Result(pdf.name, extractor.extract(pdf)))
        except (ExtractionError, json.JSONDecodeError) as e:
            results.append(Result(pdf.name, {"_confidence": "failed"}, [f"extraction failed: {e}"]))
    validate(results)
    write_outputs(results, out_dir)
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["offline", "claude"], default="offline")
    ap.add_argument("--input", type=Path, default=HERE / "samples")
    ap.add_argument("--out", type=Path, default=HERE / "output")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    a = ap.parse_args()
    extractor = OfflineExtractor() if a.mode == "offline" else ClaudeExtractor(model=a.model)
    results = run(a.input, extractor, a.out)
    for r in results:
        print(f"{r.status:<14} {r.file:<32} {'; '.join(r.issues)}")
    ok = sum(r.status == "AUTO-APPROVED" for r in results)
    print(f"\n{ok}/{len(results)} auto-approved, {len(results) - ok} sent to review -> {a.out}")


if __name__ == "__main__":
    main()
