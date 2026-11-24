"""A small mock accounting REST API (stdlib only), shaped like QuickBooks-style APIs:
OAuth2 refresh-token flow with short-lived access tokens, offset pagination
(startposition / maxresults), occasional 429 rate limits, bills that change after
creation, and an "AP aging" report total to reconcile against.
Synthetic data only - stands in for QuickBooks Online / Xero in the demo and tests."""
from __future__ import annotations

import json
import secrets
import threading
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN = "demo-client", "demo-secret", "demo-refresh-token"
AS_OF = date(2026, 11, 22)

VENDORS = [
    {"id": "V1", "name": "Lahore Paper Mills"}, {"id": "V2", "name": "ColorTech Inks"},
    {"id": "V3", "name": "PlateMakers Ltd"}, {"id": "V4", "name": "BindRight Finishing"},
    {"id": "V5", "name": "PackLine Logistics"},
]


def make_bills():
    """36 bills over ~4 months. Some paid, some part-paid, one duplicate bill number,
    one bill pointing at a vendor that no longer exists (data problem to surface)."""
    base = datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc)
    bills = []
    for i in range(1, 37):
        v = VENDORS[i % len(VENDORS)]
        txn = (base + timedelta(days=3 * i)).date()
        amount = round(150 + (i * 137) % 1900 + (i % 7) * 0.45, 2)
        paid = amount if i % 3 == 0 else (round(amount / 2, 2) if i % 8 == 0 else 0.0)
        bills.append({
            "Id": str(500 + i), "DocNumber": f"{v['id']}-{1000 + i}", "VendorRef": v["id"],
            "TxnDate": txn.isoformat(), "DueDate": (txn + timedelta(days=30)).isoformat(),
            "TotalAmt": amount, "Balance": round(amount - paid, 2),
            "LastUpdatedTime": (base + timedelta(days=3 * i, hours=2)).isoformat(),
        })
    bills[20]["DocNumber"] = bills[10]["DocNumber"]          # same vendor (V1), same number: duplicate
    bills[21]["VendorRef"] = "V9"                             # vendor deleted/merged in the ledger
    return bills


class Ledger:
    def __init__(self, bills=None, page_size=10, rate_limit_every=0, token_ttl_calls=0):
        self.bills = bills if bills is not None else make_bills()
        self.page_size, self.rate_limit_every = page_size, rate_limit_every
        self.token_ttl_calls = token_ttl_calls      # 0 = tokens never expire
        self.calls, self.token_refreshes = 0, 0
        self.tokens: dict[str, int] = {}            # access token -> calls left (-1 = unlimited)
        self.lock = threading.Lock()

    # --- helpers used by tests to simulate changes in the books ---
    def update_bill(self, bill_id, **changes):
        b = next(b for b in self.bills if b["Id"] == bill_id)
        b.update(changes)
        b["LastUpdatedTime"] = datetime.now(timezone.utc).isoformat()

    def control_total(self):
        known = {v["id"] for v in VENDORS}
        return round(sum(b["Balance"] for b in self.bills if b["VendorRef"] in known), 2)

    def handler(self):
        ledger = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, headers=None):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                if urlparse(self.path).path != "/oauth2/token":
                    return self._send(404, {"error": "not found"})
                form = parse_qs(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode())
                ok = (form.get("grant_type") == ["refresh_token"] and form.get("refresh_token") == [REFRESH_TOKEN]
                      and form.get("client_id") == [CLIENT_ID] and form.get("client_secret") == [CLIENT_SECRET])
                if not ok:
                    return self._send(400, {"error": "invalid_grant"})
                tok = secrets.token_hex(8)
                with ledger.lock:
                    ledger.tokens[tok] = ledger.token_ttl_calls or -1
                    ledger.token_refreshes += 1
                self._send(200, {"access_token": tok, "token_type": "bearer", "expires_in": 3600})

            def do_GET(self):
                with ledger.lock:
                    ledger.calls += 1
                    n = ledger.calls
                    tok = self.headers.get("Authorization", "").removeprefix("Bearer ")
                    left = ledger.tokens.get(tok)
                    if left is not None and left > 0:
                        ledger.tokens[tok] = left - 1
                    expired = left == 0
                if left is None or expired:
                    return self._send(401, {"error": "token expired" if expired else "unauthorized"})
                if ledger.rate_limit_every and n % ledger.rate_limit_every == 0:
                    return self._send(429, {"error": "rate limited"}, {"Retry-After": "0"})
                u = urlparse(self.path)
                q = parse_qs(u.query)
                if u.path == "/v3/vendors":
                    return self._send(200, {"Vendor": VENDORS})
                if u.path == "/v3/reports/ap_total":
                    return self._send(200, {"as_of": AS_OF.isoformat(), "open_balance": ledger.control_total()})
                if u.path != "/v3/bills":
                    return self._send(404, {"error": "not found"})
                since = q.get("updated_since", [""])[0]
                start = int(q.get("startposition", ["1"])[0])
                size = min(int(q.get("maxresults", [str(ledger.page_size)])[0]), ledger.page_size)
                rows = sorted((b for b in ledger.bills if b["LastUpdatedTime"] > since),
                              key=lambda b: (b["LastUpdatedTime"], b["Id"]))
                self._send(200, {"Bill": rows[start - 1:start - 1 + size], "totalCount": len(rows)})

        return H

    def serve(self, port=0):
        srv = ThreadingHTTPServer(("127.0.0.1", port), self.handler())
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv, f"http://127.0.0.1:{srv.server_address[1]}"


if __name__ == "__main__":
    srv, url = Ledger().serve(8766)
    print(f"Mock ledger API at {url}/v3/bills  Ctrl+C to stop")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.shutdown()
