"use client";

import Link from "next/link";
import { clsx } from "clsx";
import { ReactNode } from "react";

export function Card({
  children,
  className,
  action,
}: {
  children: ReactNode;
  className?: string;
  action?: ReactNode;
}) {
  return (
    <div className={clsx("card p-5", className)}>
      {action && <div className="mb-3 flex justify-end">{action}</div>}
      {children}
    </div>
  );
}

export function SectionTitle({
  title,
  action,
}: {
  title: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-3 flex items-center justify-between">
      <h2 className="text-sm font-semibold">{title}</h2>
      {action}
    </div>
  );
}

const STATUS_STYLES: Record<string, { fg: string; icon: string }> = {
  healthy: { fg: "var(--ok)", icon: "●" },
  connected: { fg: "var(--ok)", icon: "●" },
  running: { fg: "var(--info)", icon: "●" },
  suppressed: { fg: "var(--muted)", icon: "●" },
  success: { fg: "var(--ok)", icon: "●" },
  active: { fg: "var(--ok)", icon: "●" },
  delivered: { fg: "var(--ok)", icon: "●" },
  processed: { fg: "var(--ok)", icon: "●" },
  pending: { fg: "var(--warn)", icon: "◐" },
  degraded: { fg: "var(--warn)", icon: "◐" },
  waiting: { fg: "var(--warn)", icon: "◐" },
  acknowledging: { fg: "var(--warn)", icon: "◐" },
  open: { fg: "var(--err)", icon: "▲" },
  failed: { fg: "var(--err)", icon: "✕" },
  critical: { fg: "var(--err)", icon: "▲" },
  error: { fg: "var(--err)", icon: "✕" },
  dead_letter: { fg: "var(--err)", icon: "✕" },
  acknowledged: { fg: "var(--info)", icon: "◍" },
  investigating: { fg: "var(--info)", icon: "◍" },
  recovering: { fg: "var(--info)", icon: "◌" },
  resolved: { fg: "var(--ok)", icon: "✓" },
  canceled: { fg: "var(--muted, #8b96ad)", icon: "○" },
  inactive: { fg: "var(--muted, #8b96ad)", icon: "○" },
  unknown: { fg: "var(--muted, #8b96ad)", icon: "?" },
  disconnected: { fg: "var(--err)", icon: "✕" },
};

export function StatusBadge({ status }: { status?: string | null }) {
  const s = (status ?? "unknown").toLowerCase();
  const st = STATUS_STYLES[s] ?? { fg: "var(--muted, #8b96ad)", icon: "?" };
  return (
    <span
      className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-md px-2 py-1 text-[10px] font-medium capitalize"
      style={{
        color: st.fg,
        background: "color-mix(in srgb, currentColor 12%, transparent)",
      }}
    >
      <span aria-hidden className="h-1 w-1 rounded-full bg-current" />
      {s.replace("_", " ")}
    </span>
  );
}

export function SeverityBadge({ severity }: { severity?: string | null }) {
  const s = (severity ?? "unknown").toLowerCase();
  const map: Record<string, string> = {
    critical: "var(--err)",
    high: "var(--warn)",
    medium: "var(--info)",
    low: "var(--muted, #8b96ad)",
  };
  const fg = map[s] ?? "var(--muted, #8b96ad)";
  const bars =
    (
      { critical: 4, high: 3, medium: 2, normal: 2, low: 1 } as Record<
        string,
        number
      >
    )[s] ?? 0;
  return (
    <span
      className="inline-flex items-center gap-1.5 text-[11px] font-medium capitalize"
      style={{ color: fg }}
    >
      <span className="inline-flex gap-0.5" aria-hidden>
        {[0, 1, 2, 3].map((i) => (
          <span
            key={i}
            className="h-2 w-1 rounded-sm"
            style={{
              background:
                i < bars
                  ? fg
                  : "color-mix(in srgb, currentColor 20%, transparent)",
            }}
          />
        ))}
      </span>
      {s}
    </span>
  );
}

export function Empty({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="card flex flex-col items-center justify-center gap-1 p-10 text-center">
      <div className="text-sm font-medium">{title}</div>
      {hint ? (
        <div
          className="max-w-sm text-xs"
          style={{ color: "var(--muted, #8b96ad)" }}
        >
          {hint}
        </div>
      ) : null}
    </div>
  );
}

export function Skeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-2" role="status" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className="h-8 animate-pulse rounded-md"
          style={{ background: "var(--surface-2)", opacity: 1 - i * 0.15 }}
        />
      ))}
    </div>
  );
}

export function ErrorBox({
  message,
  retry,
}: {
  message: string;
  retry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex items-center justify-between gap-3 rounded-lg border px-3 py-3 text-xs"
      style={{
        borderColor: "var(--err)",
        background: "color-mix(in srgb, var(--err) 5%, var(--surface))",
      }}
    >
      <span>{message}</span>
      {retry ? (
        <button className="btn btn-secondary" onClick={retry}>
          Retry
        </button>
      ) : null}
    </div>
  );
}

export function Metric({
  label,
  value,
  onClick,
}: {
  label: string;
  value: string | number | null | undefined;
  onClick?: () => void;
}) {
  const body = (
    <div className="card p-4">
      <div
        className="text-xs font-medium uppercase tracking-wider"
        style={{ color: "var(--muted, #8b96ad)" }}
      >
        {label}
      </div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">
        {value ?? "—"}
      </div>
    </div>
  );
  return onClick ? (
    <button onClick={onClick} className="text-left">
      {body}
    </button>
  ) : (
    <div>{body}</div>
  );
}

export function LinkA({
  href,
  children,
  className,
}: {
  href: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Link href={href} className={clsx("hover:underline", className)}>
      {children}
    </Link>
  );
}
