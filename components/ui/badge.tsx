import * as React from "react";
import { cn } from "@/lib/utils";

function Badge({
  className,
  variant = "default",
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & {
  variant?: "default" | "success" | "danger" | "accent";
}) {
  const variants: Record<string, string> = {
    default: "bg-base-2 text-olive",
    success: "bg-success/15 text-success",
    danger: "bg-danger/15 text-danger",
    accent: "bg-accent text-olive",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium",
        variants[variant],
        className
      )}
      {...props}
    />
  );
}

export { Badge };
