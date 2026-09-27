"use client";

import { useAuth } from "@/lib/auth-context";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { GeneralInfoCard } from "@/components/general-info-card";

export default function SettingsPage() {
  const { user, org } = useAuth();

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-olive">Settings</h1>
        <p className="text-sm text-muted-foreground">Your account and organization.</p>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base font-semibold text-olive">Profile</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2 text-sm">
            <Row label="Name" value={user?.full_name || "—"} />
            <Row label="Email" value={user?.email ?? "—"} />
            <Row label="Role" value={user?.role ?? "member"} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base font-semibold text-olive">Organization</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2 text-sm">
            <Row label="Name" value={org?.name ?? "—"} />
            <Row label="Org ID" value={org?.id ?? "—"} />
          </CardContent>
        </Card>
      </div>

      <GeneralInfoCard />
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between border-b border-border pb-2">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}
