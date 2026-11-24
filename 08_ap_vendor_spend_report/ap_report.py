"""Demo 08: AP / vendor-spend report from an accounting API (QuickBooks-style).

Pulls bills incrementally (only those changed since the last run), refreshes the OAuth
access token when it expires, retries rate limits, reconciles open AP against the
ledger's own control total, and writes an Excel report for the finance team.
Demo project with synthetic data - runs against mock_ledger.py."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd
import requests

HERE = Path(__file__).parent
AGING_BUCKETS = [(0, "Not yet due"), (30, "1-30 days overdue"), (60, "31-60 days overdue"),
                 (90, "61-90 days overdue"), (10**6, "90+ days overdue")]


class AuthError(Exception):
    pass


class LedgerClient:
    def __init__(self, base_url, client_id, client_secret, refresh_token, backoff=0.5, max_retries=5):
        self.base, self.backoff, self.max_retries = base_url.rstrip("/"), backoff, max_retries
        self.creds = {"grant_type": "refresh_token", "refresh_token": refresh_token,
                      "client_id": client_id, "client_secret": client_secret}
        self.session, self.access_token = requests.Session(), None
        self.retries = self.refreshes = 0

    def _refresh(self):
        r = self.session.post(f"{self.base}/oauth2/token", data=self.creds, timeout=10)
        if r.status_code != 200:
            raise AuthError(f"token refresh failed: {r.status_code} {r.text[:80]}")
        self.access_token = r.json()["access_token"]
        self.refreshes += 1

    def get(self, path, **params):
        if not self.access_token:
            self._refresh()
        refreshed_this_call = False
        for attempt in range(self.max_retries + 1):
            r = self.session.get(f"{self.base}{path}", params=params, timeout=10,
                                 headers={"Authorization": f"Bearer {self.access_token}"})
            if r.status_code == 401 and not refreshed_this_call:
                self._refresh()
                refreshed_this_call = True
                continue
            if r.status_code == 401:
                raise AuthError("unauthorized after token refresh")
            if r.status_code == 429 or r.status_code >= 500:
                self.retries += 1
                time.sleep(float(r.headers.get("Retry-After", 0)) or self.backoff * 2 ** attempt)
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError(f"gave up on {path} after {self.max_retries} retries")

    def bills_since(self, since, page=10):
        start, out = 1, []
        while True:
            data = self.get("/v3/bills", updated_since=since, startposition=start, maxresults=page)
            out += data["Bill"]
            start += len(data["Bill"])
            if not data["Bill"] or start > data["totalCount"]:
                return out


@dataclass
class RunResult:
    fetched: int = 0
    total_bills: int = 0
    open_ap: float = 0.0
    control_total: float = 0.0
    reconciled: bool = False
    exceptions: list = field(default_factory=list)


def aging_bucket(due: date, as_of: date) -> str:
    overdue = (as_of - due).days
    if overdue <= 0:
        return AGING_BUCKETS[0][1]
    for limit, label in AGING_BUCKETS[1:]:
        if overdue <= limit:
            return label
    return AGING_BUCKETS[-1][1]


def run(client: LedgerClient, state: dict, as_of: date):
    """state = {"updated_since": str, "bills": {Id: bill}}. Returns (state, frames, RunResult)."""
    changed = client.bills_since(state.get("updated_since", ""))
    bills = dict(state.get("bills", {}))
    for b in changed:                      # keyed by Id: an edited bill replaces, never duplicates
        bills[b["Id"]] = b
    new_state = {"updated_since": max([state.get("updated_since", "")] + [b["LastUpdatedTime"] for b in changed]),
                 "bills": bills}

    vendors = {v["id"]: v["name"] for v in client.get("/v3/vendors")["Vendor"]}
    control = client.get("/v3/reports/ap_total")["open_balance"]
    df = pd.DataFrame(bills.values())
    res = RunResult(fetched=len(changed), total_bills=len(df), control_total=control)

    df["Vendor"] = df["VendorRef"].map(vendors)
    for _, r in df[df["Vendor"].isna()].iterrows():
        res.exceptions.append({"Bill": r.DocNumber, "Issue": f"Unknown vendor {r.VendorRef}",
                               "Amount": r.TotalAmt, "Action": "Fix vendor in the ledger; excluded from report"})
    dup = df[df.duplicated(["VendorRef", "DocNumber"], keep=False)]
    for doc, g in dup.groupby("DocNumber"):
        res.exceptions.append({"Bill": doc, "Issue": f"Duplicate bill number ({len(g)} bills, Ids {', '.join(g.Id)})",
                               "Amount": g.TotalAmt.sum(), "Action": "Check for double entry before paying"})
    ok = df[df["Vendor"].notna()].copy()
    ok["Month"] = pd.to_datetime(ok["TxnDate"]).dt.strftime("%Y-%m")
    ok["Aging"] = [aging_bucket(date.fromisoformat(d), as_of) for d in ok["DueDate"]]

    spend = ok.pivot_table(index="Vendor", columns="Month", values="TotalAmt", aggfunc="sum", fill_value=0).round(2)
    spend["Total"] = spend.sum(axis=1)
    spend = spend.sort_values("Total", ascending=False)
    open_b = ok[ok["Balance"] > 0]
    aging = open_b.pivot_table(index="Vendor", columns="Aging", values="Balance", aggfunc="sum", fill_value=0)
    aging = aging.reindex(columns=[l for _, l in AGING_BUCKETS if l in aging.columns]).round(2)
    aging["Open balance"] = aging.sum(axis=1)

    res.open_ap = round(float(open_b["Balance"].sum()), 2)
    res.reconciled = abs(res.open_ap - control) < 0.01
    if not res.reconciled:
        res.exceptions.append({"Bill": "-", "Issue": f"Open AP {res.open_ap:,.2f} ≠ ledger control {control:,.2f}",
                               "Amount": round(res.open_ap - control, 2), "Action": "Do not send report; investigate"})
    frames = {"Vendor Spend": spend, "AP Aging": aging,
              "Exceptions": pd.DataFrame(res.exceptions, columns=["Bill", "Issue", "Amount", "Action"])}
    return new_state, frames, res


def write_report(path: Path, frames: dict, res: RunResult, as_of: date, client: LedgerClient):
    summary = pd.DataFrame([
        ("As of", as_of.isoformat()), ("Bills in report", res.total_bills), ("Fetched this run", res.fetched),
        ("Open AP (report)", res.open_ap), ("Open AP (ledger control)", res.control_total),
        ("Reconciled", "YES" if res.reconciled else "NO"), ("Exceptions", len(res.exceptions)),
        ("Token refreshes", client.refreshes), ("Rate-limit retries", client.retries),
    ], columns=["Item", "Value"])
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        summary.to_excel(xw, sheet_name="Summary", index=False)
        for name, f in frames.items():
            f.to_excel(xw, sheet_name=name, index=name != "Exceptions")
        for ws in xw.book.worksheets:
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = max(12, min(60, max(len(str(c.value or "")) for c in col) + 2))


def main():
    import mock_ledger as ml
    ledger = ml.Ledger(page_size=8, rate_limit_every=5, token_ttl_calls=3)
    srv, url = ledger.serve()
    try:
        client = LedgerClient(url, ml.CLIENT_ID, ml.CLIENT_SECRET, ml.REFRESH_TOKEN, backoff=0.05)
        state_path, out = HERE / "output" / "ap_state.json", HERE / "output"
        out.mkdir(exist_ok=True)
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        state, frames, res = run(client, state, ml.AS_OF)
        state_path.write_text(json.dumps(state))
        write_report(out / "ap_vendor_report.xlsx", frames, res, ml.AS_OF, client)
        print(f"Bills {res.total_bills} (fetched {res.fetched}); open AP {res.open_ap:,.2f} vs control "
              f"{res.control_total:,.2f} -> {'RECONCILED' if res.reconciled else 'MISMATCH'}; "
              f"{len(res.exceptions)} exceptions; {client.refreshes} token refreshes; {client.retries} retries")
    finally:
        srv.shutdown()


if __name__ == "__main__":
    main()
