"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/lib/auth-context";

const STORAGE_KEY = "business_general_info";

interface GeneralInfo {
  businessType: string;
  description: string;
}

export function GeneralInfoCard() {
  const { org } = useAuth();
  const [editing, setEditing] = useState(false);
  const [info, setInfo] = useState<GeneralInfo>(() => {
    if (typeof window === "undefined") return { businessType: "", description: "" };
    try {
      return (
        JSON.parse(localStorage.getItem(STORAGE_KEY) || "null") ?? {
          businessType: "",
          description: "",
        }
      );
    } catch {
      return { businessType: "", description: "" };
    }
  });

  function save() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(info));
    setEditing(false);
  }

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle className="text-base font-semibold text-olive">
          {org?.name ?? "Your business"} — general information
        </CardTitle>
        <Button size="sm" variant="ghost" onClick={() => setEditing((v) => !v)}>
          {editing ? "Cancel" : "Edit"}
        </Button>
      </CardHeader>
      <CardContent>
        {editing ? (
          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="businessType">Business type</Label>
              <Input
                id="businessType"
                value={info.businessType}
                onChange={(e) => setInfo({ ...info, businessType: e.target.value })}
                placeholder="e.g. Retail handseller"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="description">Description</Label>
              <textarea
                id="description"
                className="min-h-24 rounded-md border border-border bg-surface p-3 text-sm focus:outline-none focus:ring-2 focus:ring-olive-soft"
                value={info.description}
                onChange={(e) => setInfo({ ...info, description: e.target.value })}
                placeholder="A short summary of your business…"
              />
            </div>
            <Button onClick={save} className="self-end">
              Save
            </Button>
          </div>
        ) : (
          <div className="text-sm text-muted-foreground">
            <p>
              <span className="font-medium text-foreground">Type: </span>
              {info.businessType || "Not set"}
            </p>
            <p className="mt-1">
              {info.description || "Add a description of your business to personalize your workspace."}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
