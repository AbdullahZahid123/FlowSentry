"use client";
import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  ArrowRight,
  Workflow,
  CircleCheck,
  BellRing,
  Activity,
  Eye,
  EyeOff,
  ArrowLeft,
  Loader2,
} from "lucide-react";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";
import { ThemeToggle } from "@/components/theme";
import { Brand } from "@/components/page";
import { ErrorBox } from "@/components/ui";
export default function LoginPage() {
  return (
    <Suspense fallback={<div className="p-10 muted">Opening FlowSentry…</div>}>
      <Login />
    </Suspense>
  );
}
function Login() {
  const router = useRouter();
  const params = useSearchParams();
  const { reload } = useSession();
  const [mode, setMode] = useState("login");
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [show, setShow] = useState(false);
  const [sent, setSent] = useState(false);
  const invite = params.get("invite");
  const reset = params.get("reset");
  async function status() {
    setChecking(true);
    setError("");
    try {
      const r = await fetch("/api/auth/system-status", {
        signal: AbortSignal.timeout(15000),
      });
      if (!r.ok)
        throw new Error(
          "The server is unavailable. Check that the API and database are running.",
        );
      const s = await r.json();
      setMode(
        s.needs_setup ? "setup" : invite ? "invite" : reset ? "reset" : "login",
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setChecking(false);
    }
  }
  useEffect(() => {
    void status();
  }, []);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    let path = "/auth/login",
      body: unknown = { email, password };
    if (mode === "setup") {
      path = "/auth/setup";
      body = {
        email,
        password,
        display_name: name || null,
        workspace_name: workspace,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      };
    }
    if (mode === "invite") {
      path = "/auth/register";
      body = {
        email,
        password,
        display_name: name || null,
        invitation_token: invite,
      };
    }
    if (mode === "forgot") {
      path = "/auth/forgot-password";
      body = { email };
    }
    if (mode === "reset") {
      path = "/auth/reset-password";
      body = { token: reset, password };
    }
    const r = await api(path, { method: "POST", body });
    setBusy(false);
    if (!r.ok) {
      setError(r.error!.message);
      return;
    }
    if (mode === "forgot") {
      setSent(true);
      return;
    }
    if (mode === "reset") {
      setMode("login");
      setPassword("");
      router.replace("/login");
      return;
    }
    await reload();
    const next = params.get("next");
    router.replace(
      next?.startsWith("/") && !next.startsWith("//") ? next : "/overview",
    );
  }
  return (
    <div className="auth-grid"><div className="fixed right-4 top-4 z-10"><ThemeToggle/></div>
      <aside className="auth-story">
        <Brand />
        <div className="mx-auto w-full max-w-md">
          <h1 className="text-[42px] font-medium leading-[1.2] tracking-[-1.8px]">Monitoring for your n8n workflows.</h1>
          <p className="muted mt-6 max-w-sm text-sm leading-7">Track executions across your instances, investigate recurring failures, and manage incidents with your team.</p>
          <ul className="mt-10 space-y-5 border-t pt-7 text-xs muted"><li>Execution history and workflow health</li><li>Shared incidents, owners, and comments</li><li>Email, Telegram, and webhook alerts</li></ul>
        </div>
        <p className="muted text-[11px]">Self-hosted · No cloud account required</p>
      </aside>
      <main className="flex items-center justify-center bg-[var(--surface)] px-6 py-12">
        <div className="w-full max-w-[350px]">
          <div className="mb-12 md:hidden">
            <Brand />
          </div>
          {checking ? (
            <div className="flex gap-2 muted">
              <Loader2 size={16} className="animate-spin" />
              Checking your installation…
            </div>
          ) : (
            <>
              <h2 className="text-[29px] font-semibold tracking-[-1px]">
                {mode === "setup"
                  ? "Create your workspace"
                  : mode === "invite"
                    ? "Accept invitation"
                    : mode === "forgot"
                      ? "Reset your password."
                      : mode === "reset"
                        ? "Choose a new password."
                        : "Sign in to FlowSentry"}
              </h2>
              <p className="muted mb-8 mt-3 text-xs leading-6">
                {mode === "setup"
                  ? "Create the owner account and your first workspace."
                  : mode === "invite"
                    ? "Create an account to accept your workspace invitation."
                    : mode === "forgot"
                      ? "Enter your account email to request a reset link."
                      : mode === "reset"
                        ? "Use at least 10 characters for your new password."
                        : "Enter your account email and password."}
              </p>
              {sent ? (
                <div
                  role="status"
                  className="rounded-lg border p-5 text-xs leading-7"
                >
                  <CircleCheck size={22} className="mb-3 text-[var(--ok)]" />
                  If an account exists, a reset has been requested. Your
                  administrator may need to configure mail delivery.
                  <button
                    className="mt-4 block text-link"
                    onClick={() => {
                      setSent(false);
                      setMode("login");
                    }}
                  >
                    Back to sign in
                  </button>
                </div>
              ) : (
                <form onSubmit={submit} className="space-y-5">
                  {mode !== "reset" && (
                    <label className="field">
                      Email address
                      <input
                        className="input !py-3"
                        type="email"
                        required
                        autoComplete="username"
                        placeholder="you@company.com"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                      />
                    </label>
                  )}
                  {mode !== "forgot" && (
                    <div>
                      <div className="mb-2 flex justify-between">
                        <label
                          htmlFor="password"
                          className="text-xs font-medium"
                        >
                          Password
                        </label>
                        {mode === "login" && (
                          <button
                            type="button"
                            className="text-[11px] text-[var(--accent)]"
                            onClick={() => {
                              setMode("forgot");
                              setError("");
                            }}
                          >
                            Forgot password?
                          </button>
                        )}
                      </div>
                      <div className="relative">
                        <input
                          id="password"
                          className="input !py-3 !pr-10"
                          type={show ? "text" : "password"}
                          required
                          minLength={mode === "login" ? undefined : 10}
                          maxLength={200}
                          autoComplete={
                            mode === "login"
                              ? "current-password"
                              : "new-password"
                          }
                          placeholder={
                            mode === "login"
                              ? "Enter your password"
                              : "At least 10 characters"
                          }
                          value={password}
                          onChange={(e) => setPassword(e.target.value)}
                        />
                        <button
                          type="button"
                          aria-label={show ? "Hide password" : "Show password"}
                          className="icon-btn absolute right-1 top-1.5"
                          onClick={() => setShow((v) => !v)}
                        >
                          {show ? <EyeOff size={15} /> : <Eye size={15} />}
                        </button>
                      </div>
                    </div>
                  )}
                  {["setup", "invite"].includes(mode) && (
                    <label className="field">
                      Your name
                      <input
                        className="input"
                        autoComplete="name"
                        maxLength={120}
                        placeholder="Optional"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                      />
                    </label>
                  )}
                  {mode === "setup" && (
                    <label className="field">
                      Workspace name
                      <input
                        className="input"
                        required
                        maxLength={120}
                        placeholder="e.g. Engineering"
                        value={workspace}
                        onChange={(e) => setWorkspace(e.target.value)}
                      />
                    </label>
                  )}
                  {error && (
                    <ErrorBox
                      message={error}
                      retry={error.includes("server") ? status : undefined}
                    />
                  )}
                  <button className="btn w-full !py-3" disabled={busy}>
                    {busy
                      ? "Please wait…"
                      : mode === "setup"
                        ? "Create workspace"
                        : mode === "invite"
                          ? "Accept invitation"
                          : mode === "forgot"
                            ? "Request reset link"
                            : mode === "reset"
                              ? "Reset password"
                              : "Sign in"}
                    <ArrowRight size={14} />
                  </button>
                  {mode === "forgot" && (
                    <button
                      type="button"
                      className="mx-auto flex items-center gap-2 text-xs muted"
                      onClick={() => {
                        setMode("login");
                        setError("");
                      }}
                    >
                      <ArrowLeft size={13} />
                      Back to sign in
                    </button>
                  )}
                </form>
              )}
              <div className="mt-9 flex items-center justify-center gap-2 border-t pt-6 text-[10px] muted">

                Your data stays on your infrastructure.
              </div>
            </>
          )}
        </div>
      </main>
    </div>
  );
}
