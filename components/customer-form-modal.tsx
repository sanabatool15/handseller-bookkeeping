"use client";

import { useEffect, useState, FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Customer, CustomerInput } from "@/lib/types";
import { customerErrorMessage } from "@/lib/use-customers";

interface CustomerFormModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initial?: Customer | null;
  onSubmit: (input: CustomerInput) => Promise<void>;
}

export function CustomerFormModal({
  open,
  onOpenChange,
  initial,
  onSubmit,
}: CustomerFormModalProps) {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [address, setAddress] = useState("");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- resets form fields when the dialog is (re)opened
    setName(initial?.name ?? "");
    setPhone(initial?.phone ?? "");
    setEmail(initial?.email ?? "");
    setAddress(initial?.address ?? "");
    setNotes(initial?.notes ?? "");
    setError(null);
  }, [open, initial]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!name.trim()) {
      setError("Name is required");
      return;
    }
    setSubmitting(true);
    try {
      // Empty optional fields are sent as null: on edit that clears them, on create it stores nothing.
      await onSubmit({
        name: name.trim(),
        phone: phone.trim() || null,
        email: email.trim() || null,
        address: address.trim() || null,
        notes: notes.trim() || null,
      });
      onOpenChange(false);
    } catch (err) {
      setError(customerErrorMessage(err, "Could not save customer"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{initial ? "Edit" : "Add"} customer</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="customer-name">Name</Label>
            <Input
              id="customer-name"
              required
              maxLength={200}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="customer-phone">Phone</Label>
              <Input
                id="customer-phone"
                maxLength={32}
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="customer-email">Email</Label>
              <Input
                id="customer-email"
                type="email"
                maxLength={320}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="customer-address">Address</Label>
            <Input
              id="customer-address"
              maxLength={500}
              value={address}
              onChange={(e) => setAddress(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="customer-notes">Notes</Label>
            <Input
              id="customer-notes"
              maxLength={1000}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </div>
          {error && <p className="text-sm text-danger">{error}</p>}
          <div className="mt-2 flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? "Saving…" : "Save"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
