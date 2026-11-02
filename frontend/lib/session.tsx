"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";

export type Membership = {
  id: string;
  name: string;
  slug: string;
  timezone: string;
  role: string;
};
export type SessionInfo = {
  id: string;
  email: string;
  name?: string;
  memberships: Membership[];
};

type SessionCtx = {
  session: SessionInfo | null;
  loading: boolean;
  workspaceId: string | null;
  setWorkspaceId: (id: string) => void;
  reload: () => Promise<void>;
};

const Ctx = createContext<SessionCtx>({
  session: null,
  loading: true,
  workspaceId: null,
  setWorkspaceId: () => {},
  reload: async () => {},
});

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [workspaceId, setWs] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const r = await fetch("/api/auth/me", {
        credentials: "include",
        signal: AbortSignal.timeout(15000),
      });
      if (r.ok) {
        const body = await r.json();
        const s: SessionInfo = {
          id: body.data.user.id,
          email: body.data.user.email,
          name: body.data.user.display_name,
          memberships: (body.data.memberships ?? []).map(
            (m: {
              workspace_id: string;
              workspace_name: string;
              workspace_slug: string;
              timezone: string;
              role: string;
            }) => ({
              id: m.workspace_id,
              name: m.workspace_name,
              slug: m.workspace_slug,
              timezone: m.timezone,
              role: m.role,
            }),
          ),
        };
        setSession(s);
        let stored = localStorage.getItem("fs_workspace");
        const active =
          s.memberships.find((m) => m.id === stored) ?? s.memberships[0];
        if (active) {
          setWs(active.id);
          localStorage.setItem("fs_workspace", active.id);
        } else {
          setWs(null);
        }
      } else {
        setSession(null);
        setWs(null);
      }
    } catch {
      setSession(null);
      setWs(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const setWorkspaceId = (id: string) => {
    setWs(id);
    localStorage.setItem("fs_workspace", id);
  };

  return (
    <Ctx.Provider
      value={{ session, loading, workspaceId, setWorkspaceId, reload }}
    >
      {children}
    </Ctx.Provider>
  );
}

export function useSession() {
  return useContext(Ctx);
}
