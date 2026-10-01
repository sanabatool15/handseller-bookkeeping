"use client";

import { Fragment, useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Pencil, Plus, Search, Trash2, Users } from "lucide-react";
import { useCustomers, customerErrorMessage } from "@/lib/use-customers";
import { Customer, CustomerSummary } from "@/lib/types";
import { formatCurrency, formatDate } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { KpiCard } from "@/components/kpi-card";
import { CustomerFormModal } from "@/components/customer-form-modal";

export default function CustomersPage() {
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  // Server-side prefix search (name or phone); debounced so typing does not fire a request per key.
  useEffect(() => {
    const t = setTimeout(() => setDebounced(query), 250);
    return () => clearTimeout(t);
  }, [query]);

  const { customers, loading, error, create, update, remove, fetchSummary } = useCustomers(debounced);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Customer | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [summary, setSummary] = useState<CustomerSummary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);

  async function toggleSummary(id: string) {
    if (expandedId === id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(id);
    setSummary(null);
    setSummaryError(null);
    try {
      const data = await fetchSummary(id);
      setSummary(data);
    } catch (e) {
      setSummaryError(customerErrorMessage(e, "Could not load summary"));
    }
  }

  async function handleDelete(id: string) {
    setActionError(null);
    try {
      await remove(id);
      if (expandedId === id) setExpandedId(null);
    } catch (e) {
      setActionError(customerErrorMessage(e, "Could not delete customer"));
    } finally {
      setConfirmDeleteId(null);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-olive">Customers</h1>
        <p className="text-sm text-muted-foreground">
          Keep your customers in one place and link them to sales.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <KpiCard
          label={debounced ? "Matching customers" : "Customers"}
          value={customers.length}
          icon={Users}
          format="number"
        />
      </div>

      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between gap-3">
          <div className="relative w-full max-w-xs">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Search by name or phone…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="pl-9"
            />
          </div>
          <Button
            onClick={() => {
              setEditing(null);
              setFormOpen(true);
            }}
          >
            <Plus className="h-4 w-4" />
            Add customer
          </Button>
        </div>

        {(error || actionError) && (
          <p className="text-sm text-danger">{actionError ?? error}</p>
        )}

        <div className="overflow-hidden rounded-lg border border-border bg-surface">
          <table className="w-full text-sm">
            <thead className="bg-base-2 text-left text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="w-8 px-2 py-3" />
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Phone</th>
                <th className="px-4 py-3">Email</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">
                    Loading…
                  </td>
                </tr>
              )}
              {!loading && customers.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">
                    {debounced ? "No customers match your search." : "No customers yet. Add your first customer above."}
                  </td>
                </tr>
              )}
              {customers.map((c) => (
                <Fragment key={c.id}>
                  <tr className="border-t border-border hover:bg-base-2">
                    <td className="px-2 py-3">
                      <Button
                        size="icon"
                        variant="ghost"
                        title={expandedId === c.id ? "Hide summary" : "Show summary"}
                        onClick={() => toggleSummary(c.id)}
                      >
                        {expandedId === c.id ? (
                          <ChevronDown className="h-4 w-4" />
                        ) : (
                          <ChevronRight className="h-4 w-4" />
                        )}
                      </Button>
                    </td>
                    <td className="px-4 py-3 font-medium">{c.name}</td>
                    <td className="px-4 py-3 text-muted-foreground">{c.phone ?? "—"}</td>
                    <td className="px-4 py-3 text-muted-foreground">{c.email ?? "—"}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          size="icon"
                          variant="ghost"
                          title="Edit"
                          onClick={() => {
                            setEditing(c);
                            setFormOpen(true);
                          }}
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <div className="relative">
                          <Button
                            size="icon"
                            variant="ghost"
                            title="Delete"
                            onClick={() => setConfirmDeleteId(c.id)}
                          >
                            <Trash2 className="h-4 w-4 text-danger" />
                          </Button>
                          {confirmDeleteId === c.id && (
                            <div className="absolute right-0 top-9 z-10 w-48 rounded-md border border-border bg-surface p-3 shadow-lg">
                              <p className="text-xs text-foreground">Delete this customer?</p>
                              <div className="mt-2 flex justify-end gap-2">
                                <Button size="sm" variant="ghost" onClick={() => setConfirmDeleteId(null)}>
                                  Cancel
                                </Button>
                                <Button size="sm" variant="danger" onClick={() => handleDelete(c.id)}>
                                  Delete
                                </Button>
                              </div>
                            </div>
                          )}
                        </div>
                      </div>
                    </td>
                  </tr>
                  {expandedId === c.id && (
                    <tr className="border-t border-border bg-base-2">
                      <td />
                      <td colSpan={4} className="px-4 py-3">
                        {summaryError && <p className="text-sm text-danger">{summaryError}</p>}
                        {!summaryError && !summary && (
                          <p className="text-sm text-muted-foreground">Loading summary…</p>
                        )}
                        {summary && summary.customer.id === c.id && (
                          <dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-3">
                            <div>
                              <dt className="text-xs uppercase tracking-wide text-muted-foreground">Total sales</dt>
                              <dd className="font-medium tabular-nums">{formatCurrency(summary.total_sales)}</dd>
                            </div>
                            <div>
                              <dt className="text-xs uppercase tracking-wide text-muted-foreground">Sales count</dt>
                              <dd className="font-medium tabular-nums">{summary.sale_count}</dd>
                            </div>
                            <div>
                              <dt className="text-xs uppercase tracking-wide text-muted-foreground">Last sale</dt>
                              <dd className="font-medium">
                                {summary.last_sale_date ? formatDate(summary.last_sale_date) : "—"}
                              </dd>
                            </div>
                            {(c.address || c.notes) && (
                              <div className="sm:col-span-3 text-muted-foreground">
                                {c.address && <p>Address: {c.address}</p>}
                                {c.notes && <p>Notes: {c.notes}</p>}
                              </div>
                            )}
                          </dl>
                        )}
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <CustomerFormModal
        open={formOpen}
        onOpenChange={setFormOpen}
        initial={editing}
        onSubmit={(input) => (editing ? update(editing.id, input) : create(input))}
      />
    </div>
  );
}
