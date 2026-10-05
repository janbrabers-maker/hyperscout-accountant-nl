# Hyperscout Accountant NL

Bookkeeping skill for Hyperscout Holding B.V. (Den Haag). Collects and books invoices, keeps the
ledger "Hyperscout Holding books ledger" in Google Drive, lists missing invoices, and builds the
monthly overview (PDF) and the quarterly BTW file for Serdal (Excel).

- `SKILL.md`: the skill (instructions plus the report script, embedded).
- `scripts/acc_report.py`: the same report script as a standalone file.

All data lives in the Drive folder "Hyperscout Holding books". Nothing confidential is stored in this repo.

## Hyperscout Italia S.r.l. (italia/)

The Italian bookkeeper lives in `italia/`: `SKILL.md` (skill hyperscout-accountant-it), `scripts/acc_report_it.py` (monthly and quarterly PDF for Jan, IVA Excel in Italian for the commercialista) and `books_it.html` (the web page "Hyperscout Italia Books"). Same set-up as the Dutch books: one Drive folder "Hyperscout Italia books" with a ledger sheet and month folders, a web page for Jan, and the find-then-check flow for invoices.
