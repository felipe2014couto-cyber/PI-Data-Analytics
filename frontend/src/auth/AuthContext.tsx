import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { authApi } from "../api";
import type { AuthUser } from "../types";

interface AuthContextValue { user: AuthUser | null; loading: boolean; login: (username: string, password: string) => Promise<AuthUser>; logout: () => Promise<void>; refresh: () => Promise<void>; changePassword: (currentPassword: string, newPassword: string) => Promise<void>; }
const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null); const [loading, setLoading] = useState(true);
  const refresh = useCallback(async () => { try { setUser(await authApi.me()); } catch { setUser(null); } finally { setLoading(false); } }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => { const handler = () => setUser(null); window.addEventListener("pads:unauthorized", handler); return () => window.removeEventListener("pads:unauthorized", handler); }, []);
  const login = async (username: string, password: string) => { const authenticated = await authApi.login(username, password); setUser(authenticated); return authenticated; };
  const logout = async () => { try { await authApi.logout(); } finally { setUser(null); } };
  const changePassword = async (currentPassword: string, newPassword: string) => { setUser(await authApi.changePassword(currentPassword, newPassword)); };
  const value = useMemo(() => ({ user, loading, login, logout, refresh, changePassword }), [user, loading, refresh]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
export function useAuth() { const value = useContext(AuthContext); if (!value) throw new Error("AuthProvider ausente"); return value; }
