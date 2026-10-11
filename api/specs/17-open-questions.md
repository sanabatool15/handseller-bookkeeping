# 17. Choices that were made (and could change)

## In one line
While building, the AI had to guess some things. The important guesses are listed here with the reason.

## The main choices

| Choice | Why |
|---|---|
| Emails and SKUs ignore upper/lower case | SQL Server does this by default |
| Deleting a customer who has sales is refused | deleting would damage the sales history. Remove the link from the sales first |
| A sale links to a customer through `customer_id` **and** `org_id` | the database itself stops links to another business's customer |
| Procedures return "not enough stock" as a message, not a crash | a crash would undo the caller's other work too |
| Called from SSMS, the procedure saves by itself. Called from the app, the app saves at the end | depends on whether a transaction is already open |
| Cash balance may go below zero | a seller can spend before cashing up |
| Old sales and expenses (from before the ledger) are not added to the ledger | there is no "opening balance" yet |
| Changing a sale amount adds an adjustment row to the ledger | so the balance stays correct |
| A product that was sold cannot be deleted | mark it inactive instead |
| Saving now happens before the answer is sent to the browser | so the browser never sees a result that is not saved yet |
| DB Lab "safe" race only changes stock | so the demo leaves no sales or ledger rows behind |

## Known limits
* The stock change has no history table. The "reason" typed on a stock change is not saved.
* Activity and Cash pages show only the newest rows (no page buttons).
* Deleting a sold product shows a clear message only on an English SQL Server.
* Some features (void, expenses, cash edits, DB Lab buttons) still need a person to try them on the real server.

## Questions a teacher may ask
* **Why can the cash balance be negative?** A business choice. A guard is easy to add.
* **Why not delete a customer with sales?** To protect history.
* **Why does the procedure behave differently in SSMS and in the app?** SSMS has no transaction open, so the procedure opens and saves its own. The app already has one open, so the app saves at the end.
