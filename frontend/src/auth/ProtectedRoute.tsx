import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "./AuthContext";
export function ProtectedRoute({ admin = false }: { admin?: boolean }) { const { user, loading } = useAuth(); const location = useLocation(); if (loading) return <div className="p-4">Verificando sessão...</div>; if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />; if (user.must_change_password) return <Navigate to="/trocar-senha" replace />; if (admin && user.role !== "admin") return <Navigate to="/" replace />; return <Outlet />; }
