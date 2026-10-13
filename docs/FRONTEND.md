# Frontend (Next.js)

The website the seller uses. It only shows data and sends requests; all rules and SQL live in the backend ([BACKEND.md](BACKEND.md)).

## How to run
```
npm install
npm run dev          # http://localhost:3000
```
The backend must be running on port 8000 (see the main [README](../README.md)). The browser calls `/api/...`; `next.config.ts` forwards that to `http://localhost:8000/api/...`.

## Where things are

| Folder / file | What it is |
|---|---|
| `app/(auth)/login`, `app/(auth)/register` | login and register pages |
| `app/(app)/<name>/page.tsx` | one page each: dashboard, sales, expenses, cash, products, customers, activity, db-lab, settings |
| `components/` | shared pieces: forms in popups, tables, KPI cards, charts, `layout/sidebar.tsx` |
| `components/ui/` | small building blocks (button, input, card, dialog...) |
| `lib/api-client.ts` | one function that calls the backend. It adds the login token and a fresh `Idempotency-Key` to every save |
| `lib/auth-context.tsx` | who is logged in (token kept in the browser) |
| `lib/use-*.ts` | one hook per feature that loads and saves data (products, customers, cash, activity, db lab) |
| `lib/types.ts` | the shapes of the data coming from the backend |

## Checks
```
npm run lint
npx tsc --noEmit
```

## The pages in detail

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
