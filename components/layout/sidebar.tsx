"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Receipt,
  Wallet,
  Package,
  Sparkles,
  Settings,
  LogOut,
} from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/advisor", label: "AI Agent Advisor", icon: Sparkles },
  { href: "/sales", label: "Sales", icon: Receipt },
  { href: "/expenses", label: "Expenses", icon: Wallet },
  { href: "/products", label: "Products", icon: Package },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();
  const { org, logout } = useAuth();

  return (
    <aside className="flex h-screen w-64 flex-col justify-between border-l border-border bg-olive text-white">
      <div>
        <div className="px-6 py-6">
          <p className="text-xs uppercase tracking-wide text-accent">
            Workspace
          </p>
          <p className="mt-1 truncate text-lg font-semibold">
            {org?.name ?? "Your Business"}
          </p>
        </div>
        <nav className="flex flex-col gap-1 px-3">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = pathname?.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex items-center gap-3 rounded-md px-3 py-2.5 text-sm font-medium transition-colors",
                  active
                    ? "bg-accent text-olive"
                    : "text-white/85 hover:bg-white/10"
                )}
              >
                <Icon className="h-4 w-4" />
                {label}
              </Link>
            );
          })}
        </nav>
      </div>
      <div className="px-3 pb-6">
        <button
          onClick={logout}
          className="flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-sm font-medium text-white/85 hover:bg-white/10"
        >
          <LogOut className="h-4 w-4" />
          Log out
        </button>
      </div>
    </aside>
  );
}
