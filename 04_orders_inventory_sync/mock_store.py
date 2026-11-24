"""A small mock e-commerce REST API (stdlib only) that behaves like real ones:
bearer-token auth, cursor pagination, occasional 429 rate limits, and order status changes.
Synthetic data - stands in for Shopify/WooCommerce-style APIs in the demo and tests."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

TOKEN = "demo-token"


def make_orders(n=23):
    base = datetime(2026, 11, 17, 8, 0, tzinfo=timezone.utc)
    skus = ["NB-A5-RULED", "NB-A4-PLAIN", "PEN-BLUE-10", "FILE-BOX", "DIARY-2027"]
    orders = []
    for i in range(1, n + 1):
        lines = [{"sku": skus[(i + k) % len(skus)], "quantity": 1 + (i * (k + 2)) % 4} for k in range(1 + i % 3)]
        orders.append({"id": 1000 + i, "status": "paid",
                       "updated_at": (base + timedelta(minutes=17 * i)).isoformat(), "lines": lines})
    orders[4]["status"] = "cancelled"          # cancelled before fulfilment
    orders[9]["lines"].append({"sku": "UNKNOWN-SKU", "quantity": 1})  # data problem to surface
    return orders


class Store:
    def __init__(self, orders=None, page_size=10, rate_limit_every=0):
        self.orders = orders or make_orders()
        self.page_size, self.rate_limit_every, self.calls = page_size, rate_limit_every, 0
        self.lock = threading.Lock()

    def handler(self):
        store = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # keep test output quiet
                pass

            def _send(self, code, body, headers=None):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                with store.lock:
                    store.calls += 1
                    n = store.calls
                if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                    return self._send(401, {"error": "unauthorized"})
                if store.rate_limit_every and n % store.rate_limit_every == 0:
                    return self._send(429, {"error": "rate limited"}, {"Retry-After": "0"})
                u = urlparse(self.path)
                if u.path != "/api/orders":
                    return self._send(404, {"error": "not found"})
                q = parse_qs(u.query)
                since = q.get("updated_since", [""])[0]
                cursor = int(q.get("cursor", ["0"])[0])
                rows = sorted((o for o in store.orders if o["updated_at"] > since), key=lambda o: o["updated_at"])
                page = rows[cursor:cursor + store.page_size]
                nxt = cursor + store.page_size if cursor + store.page_size < len(rows) else None
                self._send(200, {"orders": page, "next_cursor": nxt})

        return H

    def serve(self, port=0):
        srv = ThreadingHTTPServer(("127.0.0.1", port), self.handler())
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv, f"http://127.0.0.1:{srv.server_address[1]}"


if __name__ == "__main__":
    srv, url = Store().serve(8765)
    print(f"Mock store running at {url}/api/orders  (token: {TOKEN})  Ctrl+C to stop")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.shutdown()
