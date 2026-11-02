"use client";
import { ReactNode, useState, useRef } from "react";
import {
  ArrowUpRight,
  Workflow,
  Search,
  ArrowRight,
  Check,
  Copy,
} from "lucide-react";
import Link from "next/link";
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
export function PageHeading({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action && <div className="flex min-w-0 flex-wrap items-center gap-2 pt-1">{action}</div>}
    </div>
  );
}
export function PanelHeading({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="section-heading">
      <div>
        <h2>{title}</h2>
        {description && <p>{description}</p>}
      </div>
      {action}
    </div>
  );
}
export function Brand({ small = false }: { small?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <span className="logo-mark">
        <Workflow size={21} />
      </span>
      <span
        className={
          small
            ? "font-semibold text-base tracking-tight"
            : "text-xl font-semibold tracking-tight"
        }
      >
        FlowSentry<span className="text-[#ff6d5a]">.</span>
      </span>
    </div>
  );
}
export function SearchInput({
  value,
  onChange,
  placeholder = "Search…",
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <div className="filter-search">
      <Search size={14} />
      <input
        aria-label={placeholder}
        className="input"
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}
export function ViewAll({
  href,
  children = "View all",
}: {
  href: string;
  children?: ReactNode;
}) {
  return (
    <Link className="text-link" href={href}>
      {children}
      <ArrowUpRight size={13} />
    </Link>
  );
}
export function FormDialog({
  open,
  onOpenChange,
  title,
  description,
  children,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title: string;
  description: string;
  children: ReactNode;
}) {
  const focusReturn = useRef<HTMLElement | null>(null);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90svh] w-[calc(100%-32px)] max-w-[480px] overflow-y-auto rounded-lg"
        onOpenAutoFocus={() => { focusReturn.current = document.activeElement as HTMLElement; }}
        onCloseAutoFocus={event => { if (focusReturn.current?.isConnected) { event.preventDefault(); focusReturn.current.focus(); } }}>
        <DialogTitle className="text-xl tracking-tight">{title}</DialogTitle>
        <DialogDescription>{description}</DialogDescription>
        {children}
      </DialogContent>
    </Dialog>
  );
}
export function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="btn btn-secondary"
      onClick={async () => {
        await navigator.clipboard.writeText(value);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }}
    >
      {copied ? <Check size={14} /> : <Copy size={14} />}{" "}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}
export function SetupEmpty({
  title,
  description,
  href = "/integrations",
  action = "Connect an integration",
}: {
  title: string;
  description: string;
  href?: string;
  action?: string;
}) {
  return (
    <div className="flex min-h-60 flex-col items-center justify-center px-5 py-10 text-center">
      <span className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl border bg-[var(--surface-2)]">
        <Workflow size={20} className="muted" />
      </span>
      <h3 className="text-sm font-semibold">{title}</h3>
      <p className="muted mt-2 max-w-sm text-xs leading-6">{description}</p>
      <Link href={href} className="btn btn-secondary mt-5">
        {action}
        <ArrowRight size={13} />
      </Link>
    </div>
  );
}
