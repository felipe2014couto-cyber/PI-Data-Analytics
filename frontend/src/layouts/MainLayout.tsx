import { FormEvent, useState } from "react";
import { Link, NavLink, Outlet } from "react-router-dom";
import { Button, Form, Modal } from "react-bootstrap";

import { APP_NAME } from "../utils/app";
import { useAuth } from "../auth/AuthContext";
import { authApi } from "../api";

interface NavItem {
  to: string;
  label: string;
  icon: string;
}

const CADASTROS_ITEMS: NavItem[] = [
  { to: "/cadastros/equipamentos", label: "Equipamentos", icon: "bi-gear" },
  { to: "/cadastros/secoes", label: "Seções", icon: "bi-diagram-3" },
  { to: "/cadastros/tipos-variavel", label: "Tipos de Variável", icon: "bi-tags" },
  { to: "/cadastros/tags-pi", label: "Tags Temporais", icon: "bi-bookmark-star" },
  { to: "/cadastros/tags-banco", label: "Tags de Banco", icon: "bi-database" },
];

const ANALISES_ITEMS: NavItem[] = [
  { to: "/analises/visualizacao", label: "Visualização de Dados", icon: "bi-graph-up" },
  { to: "/analises/cep", label: "Análise CEP", icon: "bi-clipboard-data" },
];

function Sidebar({ open, onClose, admin }: { open: boolean; onClose: () => void; admin: boolean }) {
  return (
    <>
      {open ? <div className="app-sidebar__backdrop" onClick={onClose} /> : null}
      <aside className={`app-sidebar ${open ? "open" : ""}`} aria-label="Menu principal">
        <Link to="/" className="app-sidebar__brand" onClick={onClose} aria-label={`${APP_NAME} — início`}>
          <span className="app-sidebar__brand-mark">PI</span>
          <span className="app-sidebar__brand-name">{APP_NAME}</span>
        </Link>
        <nav className="app-sidebar__nav">
          <div className="app-sidebar__section">Cadastros</div>
          {CADASTROS_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => `app-sidebar__link ${isActive ? "active" : ""}`}
              onClick={onClose}
            >
              <i className={`bi ${item.icon}`} aria-hidden="true" />
              <span className="app-sidebar__link-label">{item.label}</span>
              <i className="bi bi-chevron-right app-sidebar__chevron" aria-hidden="true" />
            </NavLink>
          ))}
          <div className="app-sidebar__section app-sidebar__section--divided">Análises</div>
          {ANALISES_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => `app-sidebar__link ${isActive ? "active" : ""}`}
              onClick={onClose}
            >
              <i className={`bi ${item.icon}`} aria-hidden="true" />
              <span className="app-sidebar__link-label">{item.label}</span>
              <i className="bi bi-chevron-right app-sidebar__chevron" aria-hidden="true" />
            </NavLink>
          ))}
          {admin ? <>
            <NavLink to="/admin/usuarios" className={({ isActive }) => `app-sidebar__link ${isActive ? "active" : ""}`} onClick={onClose}><i className="bi bi-people" aria-hidden="true" /><span className="app-sidebar__link-label">Usuários</span><i className="bi bi-chevron-right app-sidebar__chevron" aria-hidden="true" /></NavLink>
            <NavLink to="/admin/recargas-historicas" className={({ isActive }) => `app-sidebar__link ${isActive ? "active" : ""}`} onClick={onClose}><i className="bi bi-cloud-download" aria-hidden="true" /><span className="app-sidebar__link-label">Recargas históricas</span><i className="bi bi-chevron-right app-sidebar__chevron" aria-hidden="true" /></NavLink>
            <NavLink to="/admin/saude-banco" className={({ isActive }) => `app-sidebar__link ${isActive ? "active" : ""}`} onClick={onClose}><i className="bi bi-database-check" aria-hidden="true" /><span className="app-sidebar__link-label">Saúde do Banco</span><i className="bi bi-chevron-right app-sidebar__chevron" aria-hidden="true" /></NavLink>
          </> : null}
        </nav>
      </aside>
    </>
  );
}

function Topbar({ onToggleSidebar, pageTitle, username, onLogout, onPassword }: { onToggleSidebar: () => void; pageTitle: string; username: string; onLogout: () => void; onPassword: () => void }) {
  return (
    <header className="app-topbar">
      <div className="d-flex align-items-center gap-2">
        <button
          type="button"
          className="btn btn-outline-secondary btn-sm d-lg-none"
          onClick={onToggleSidebar}
          aria-label="Abrir menu"
        >
          <i className="bi bi-list" />
        </button>
        <div>
          <div className="app-topbar__title">{pageTitle}</div>
          <div className="app-topbar__subtitle">{APP_NAME}</div>
        </div>
      </div>
      <div className="d-flex align-items-center gap-2 small">
        <span>{username}</span><Button size="sm" variant="outline-secondary" onClick={onPassword}>Alterar senha</Button><Button size="sm" variant="outline-danger" onClick={onLogout}>Sair</Button>
      </div>
    </header>
  );
}

export function MainLayout() {
  const { user, logout } = useAuth();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [showPassword, setShowPassword] = useState(false); const [currentPassword, setCurrentPassword] = useState(""); const [newPassword, setNewPassword] = useState(""); const [passwordError, setPasswordError] = useState<string | null>(null);
  const pageTitle = "PI Analytics Data";

  return (
    <div className="app-shell">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} admin={user?.role === "admin"} />
      <div className="app-main">
        <Topbar onToggleSidebar={() => setSidebarOpen((open) => !open)} pageTitle={pageTitle} username={user?.username ?? ""} onLogout={() => void logout()} onPassword={() => setShowPassword(true)} />
        <main className="app-content">
          <Outlet />
        </main>
        <footer className="app-footer d-flex justify-content-between flex-wrap gap-2">
          <span>{APP_NAME} - Fase 1 (POC de cadastros).</span>
          <span className="text-muted">PI Web API nao consultado nesta fase.</span>
        </footer>
        <Modal show={showPassword} onHide={() => setShowPassword(false)}><Form onSubmit={async (event: FormEvent) => { event.preventDefault(); try { await authApi.changePassword(currentPassword, newPassword); setShowPassword(false); await logout(); } catch { setPasswordError("Não foi possível alterar a senha."); } }}><Modal.Header closeButton><Modal.Title>Alterar senha</Modal.Title></Modal.Header><Modal.Body>{passwordError ? <div className="text-danger mb-2">{passwordError}</div> : null}<Form.Group className="mb-2"><Form.Label>Senha atual</Form.Label><Form.Control type="password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} required /></Form.Group><Form.Group><Form.Label>Nova senha</Form.Label><Form.Control type="password" minLength={5} maxLength={128} value={newPassword} onChange={(e) => setNewPassword(e.target.value)} required /></Form.Group></Modal.Body><Modal.Footer><Button variant="secondary" onClick={() => setShowPassword(false)}>Cancelar</Button><Button type="submit">Alterar</Button></Modal.Footer></Form></Modal>
      </div>
    </div>
  );
}
