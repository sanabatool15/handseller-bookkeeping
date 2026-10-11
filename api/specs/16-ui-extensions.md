# 16. The new pages

## In one line
Five new pages in the sidebar. Each one shows a database feature.

| Page | What you do there | What it shows |
|---|---|---|
| **Products** | add products, set price and stock, change stock, see low stock | rules (CHECK, UNIQUE), safe stock change |
| **Customers** | add customers, search by name or phone, see total bought | unique phone, links between tables |
| **Cash** | see the balance, a monthly summary, every money movement | the cash ledger |
| **Activity** | see each money request and its result | transactions, retry after deadlock |
| **DB Lab** | press buttons to create a race or a deadlock | race condition, deadlock |

## Demo order for a teacher (about 5 minutes)
1. **Products:** create a product with stock 1.
2. **Sales:** sell 1. Stock becomes 0 and cash goes up. Try to sell 1 more: the app says "not enough stock" and nothing changes.
3. **Cash:** show the new ledger line and the balance.
4. **Activity:** show the successful request and the refused one.
5. **DB Lab** (needs `ENABLE_DB_LAB=true`):
   * Race sale, `unsafe` mode: the last item is sold more than once (oversold).
   * Race sale, `safe` mode: one winner, the others are refused.
   * Force deadlock: one client gets error 1205 and retries.
   * Deadlock fixed: nobody is cancelled.

## Words on the Activity page
* **committed**: saved.
* **deadlock, retried**: a deadlock happened, the app tried again and it was saved.
* **rejected**: a business rule said no (for example not enough stock).
* **rolled back**: an error happened and the work was undone.
* **lock wait suspected**: a guess, because the request took long.

## Questions a teacher may ask
* **Why does DB Lab exist?** To see concurrency problems live.
* **Is it safe?** It is a demo only. It puts the stock back afterwards. Never turn it on for real users.
* **Rejected vs rolled back?** Rejected = a rule said no. Rolled back = an error undid the work.
