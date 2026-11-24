"""
DEMO PROJECT (sample data) - Store orders -> inventory sync.

Pulls new and changed orders from a store's REST API (bearer auth, cursor pagination,
429 retry with backoff), applies them to the stock sheet exactly once (idempotent by order
id + status), puts stock back for cancelled orders, flags unknown SKUs, and raises
low-stock alerts. State lives in a small JSON file, so each run only fetches what changed.

Usage:
    python sync.py                 # runs against the bundled mock store
    python sync.py --base-url https://store.example.com --token $TOKEN   # real API (adapter per platform)
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import requests

HERE = Path(__file__).parent


class ApiError(Exception):
    pass


class StoreClient:
    def __init__(self, base_url: str, token: str, session=None, max_retries=4, backoff=0.5):
        self.base_url, self.max_retries, self.backoff = base_url.rstrip("/"), max_retries, backoff
        self.s = session or requests.Session()
        self.s.headers["Authorization"] = f"Bearer {token}"
        self.retries_used = 0

    def _get(self, path, params):
        for attempt in range(self.max_retries + 1):
            r = self.s.get(f"{self.base_url}{path}", params=params, timeout=20)
            if r.status_code == 429 or r.status_code >= 500:
                if attempt == self.max_retries:
                    raise ApiError(f"{r.status_code} after {attempt} retries")
                self.retries_used += 1
                time.sleep(float(r.headers.get("Retry-After", self.backoff * 2 ** attempt)))
                continue
            if r.status_code == 401:
                raise ApiError("401 unauthorized - check the API token")
            r.raise_for_status()
            return r.json()
        raise ApiError("unreachable")  # pragma: no cover

    def orders_since(self, updated_since: str):
        cursor = 0
        while cursor is not None:
            page = self._get("/api/orders", {"updated_since": updated_since, "cursor": cursor})
            yield from page["orders"]
            cursor = page["next_cursor"]


@dataclass
class SyncResult:
    fetched: int = 0
    applied: int = 0
    skipped_duplicates: int = 0
    restocked: int = 0
    unknown_skus: list = field(default_factory=list)
    low_stock: pd.DataFrame | None = None
    retries: int = 0


def load_state(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {"updated_since": "", "applied": {}}  # applied: order_id -> status already applied


def sync(client: StoreClient, stock: pd.DataFrame, state: dict) -> tuple[pd.DataFrame, dict, SyncResult]:
    stock = stock.set_index("sku").copy()
    res = SyncResult()
    latest = state["updated_since"]
    for order in client.orders_since(state["updated_since"]):
        res.fetched += 1
        oid, status = str(order["id"]), order["status"]
        latest = max(latest, order["updated_at"])
        prev = state["applied"].get(oid)
        if prev == status:
            res.skipped_duplicates += 1
            continue
        if status == "paid" and prev is None:
            sign = -1
        elif status == "cancelled" and prev == "paid":
            sign, res.restocked = +1, res.restocked + 1
        else:                      # e.g. cancelled before we ever deducted: just record it
            state["applied"][oid] = status
            continue
        for line in order["lines"]:
            if line["sku"] not in stock.index:
                res.unknown_skus.append(f"order {oid}: {line['sku']}")
                continue
            stock.loc[line["sku"], "on_hand"] += sign * line["quantity"]
        state["applied"][oid] = status
        res.applied += 1
    state["updated_since"] = latest
    res.retries = client.retries_used
    stock = stock.reset_index()
    res.low_stock = stock[stock.on_hand <= stock.reorder_level]
    return stock, state, res


def write_outputs(stock: pd.DataFrame, res: SyncResult, out: Path):
    out.mkdir(exist_ok=True)
    stock.to_csv(out / "stock_after_sync.csv", index=False)
    with pd.ExcelWriter(out / "sync_report.xlsx", engine="openpyxl") as xw:
        stock.to_excel(xw, sheet_name="Stock", index=False)
        res.low_stock.to_excel(xw, sheet_name="Low Stock", index=False)
        pd.DataFrame({"unknown_sku": res.unknown_skus}).to_excel(xw, sheet_name="Data Problems", index=False)
        pd.DataFrame([{"fetched": res.fetched, "applied": res.applied, "duplicates_skipped":
                       res.skipped_duplicates, "restocked_cancellations": res.restocked,
                       "api_retries": res.retries}]).to_excel(xw, sheet_name="Run Log", index=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url")
    ap.add_argument("--token", default="demo-token")
    ap.add_argument("--stock", type=Path, default=HERE / "data" / "stock.csv")
    ap.add_argument("--state", type=Path, default=HERE / "output" / "sync_state.json")
    a = ap.parse_args()
    srv = store = None
    if not a.base_url:
        import mock_store
        store = mock_store.Store(rate_limit_every=4)
        srv, a.base_url = store.serve()
        print(f"Using mock store at {a.base_url}")
    a.state.parent.mkdir(exist_ok=True)
    stock = pd.read_csv(a.stock)
    for run in (1, 2):
        if run == 2 and store:  # demo: between runs a customer cancels a paid order
            o = next(o for o in store.orders if o["id"] == 1003)
            o["status"], o["updated_at"] = "cancelled", "2026-11-18T12:00:00+00:00"
        state = load_state(a.state)
        client = StoreClient(a.base_url, a.token, backoff=0.05)
        stock, state, res = sync(client, stock, state)
        a.state.write_text(json.dumps(state, indent=1))
        print(f"run {run}: fetched {res.fetched}, applied {res.applied}, duplicates skipped "
              f"{res.skipped_duplicates}, restocked {res.restocked}, API retries {res.retries}, "
              f"unknown SKUs {res.unknown_skus}")
    write_outputs(stock, res, a.state.parent)
    print("\nLow stock:\n" + res.low_stock.to_string(index=False))
    if srv:
        srv.shutdown()


if __name__ == "__main__":
    main()
