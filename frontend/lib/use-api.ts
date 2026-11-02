"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiResult } from "@/lib/api";
import { useSession } from "@/lib/session";
export function useApi<T>(
  path: string,
  query?: Record<string, string | number | undefined>,
) {
  const { workspaceId } = useSession();
  const signature = JSON.stringify(query ?? {});
  const key = `${workspaceId}:${path}:${signature}`;
  const current = useRef(key);
  current.current = key;
  const [state, setState] = useState<{
    key: string;
    result?: ApiResult<T>;
    loading: boolean;
  }>({ key, loading: true });
  const reload = useCallback(async () => {
    if (!workspaceId) return;
    const requested = `${workspaceId}:${path}:${signature}`;
    const result = await api<T>(path, {
      workspaceId,
      query: JSON.parse(signature),
    });
    if (current.current === requested)
      setState({ key: requested, result, loading: false });
  }, [workspaceId, path, signature]);
  useEffect(() => {
    setState({ key, loading: true });
    void reload();
    const refresh = () => {
      void reload();
    };
    window.addEventListener("fs:refresh", refresh);
    return () => window.removeEventListener("fs:refresh", refresh);
  }, [key, reload]);
  const valid = state.key === key;
  return {
    data: valid ? state.result?.data : undefined,
    meta: valid ? state.result?.meta : undefined,
    error: valid ? state.result?.error?.message : undefined,
    loading: !valid || state.loading,
    reload,
  };
}
