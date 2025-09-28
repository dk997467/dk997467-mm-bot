Ledger Reports
==============

Fields:
- Daily (LEDGER_DAILY.json): date, pnl, fees, rebates, turnover, equity
- Equity (LEDGER_EQUITY.json): ts, equity

Notes:
- Fees positive reduce cash; rebates negative (as credit) increase cash
- Mark-to-market uses last mid per symbol
- Daily close resets aggregates (positions/cash persist)

Serialization: deterministic JSON (ensure_ascii, sort_keys, separators), trailing \n.


