import { FormEvent, useEffect, useState } from "react";
import { Alert, Button, Card, Form, Modal, Table } from "react-bootstrap";
import { adminUsersApi } from "../api";
import type { AuthUser, UserRole } from "../types";

export function AdminUsersPage() {
  const [users, setUsers] = useState<AuthUser[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<UserRole>("user");
  const [resetUser, setResetUser] = useState<AuthUser | null>(null);
  const [resetPassword, setResetPassword] = useState("");

  const load = async () => {
    try { setUsers(await adminUsersApi.list()); setError(null); }
    catch { setError("Não foi possível carregar os usuários."); }
  };
  useEffect(() => { void load(); }, []);

  const create = async (event: FormEvent) => {
    event.preventDefault();
    try { await adminUsersApi.create({ username, password, role }); setShowCreate(false); setUsername(""); setPassword(""); await load(); }
    catch { setError("Não foi possível criar o usuário. Verifique nome e senha."); }
  };
  const update = async (user: AuthUser, patch: { role?: UserRole; is_active?: boolean }) => {
    if (!window.confirm(`Confirmar alteração de ${user.username}?`)) return;
    try { await adminUsersApi.update(user.id, patch); await load(); }
    catch { setError("Alteração rejeitada. Verifique a proteção do último administrador."); }
  };
  const rename = async (user: AuthUser) => {
    const next = window.prompt("Novo nome de usuário", user.username)?.trim();
    if (!next || next === user.username) return;
    try { await adminUsersApi.update(user.id, { username: next }); await load(); }
    catch { setError("Não foi possível renomear o usuário."); }
  };
  const reset = async (event: FormEvent) => {
    event.preventDefault();
    if (!resetUser || !window.confirm(`Redefinir a senha de ${resetUser.username}?`)) return;
    try { await adminUsersApi.resetPassword(resetUser.id, resetPassword); setResetUser(null); setResetPassword(""); }
    catch { setError("Não foi possível redefinir a senha."); }
  };

  return <>
    <Card className="piad-card">
      <Card.Header className="d-flex justify-content-between"><span>Gestão de usuários</span><Button size="sm" onClick={() => setShowCreate(true)}>Novo usuário</Button></Card.Header>
      <Card.Body>
        {error ? <Alert variant="danger">{error}</Alert> : null}
        <Table responsive><thead><tr><th>Usuário</th><th>Perfil</th><th>Estado</th><th>Ações</th></tr></thead><tbody>
          {users.map((user) => <tr key={user.id}><td>{user.username}</td><td>{user.role}</td><td>{user.is_active ? "Ativo" : "Inativo"}</td><td className="d-flex gap-1">
            <Button size="sm" variant="outline-secondary" onClick={() => void rename(user)}>Renomear</Button>
            <Button size="sm" variant="outline-secondary" onClick={() => void update(user, { role: user.role === "admin" ? "user" : "admin" })}>Alterar perfil</Button>
            <Button size="sm" variant="outline-warning" onClick={() => void update(user, { is_active: !user.is_active })}>{user.is_active ? "Desativar" : "Ativar"}</Button>
            <Button size="sm" variant="outline-danger" onClick={() => setResetUser(user)}>Redefinir senha</Button>
          </td></tr>)}
        </tbody></Table>
      </Card.Body>
    </Card>
    <Modal show={showCreate} onHide={() => setShowCreate(false)}><Form onSubmit={create}>
      <Modal.Header closeButton><Modal.Title>Novo usuário</Modal.Title></Modal.Header><Modal.Body>
        <Form.Group className="mb-2"><Form.Label>Usuário</Form.Label><Form.Control value={username} onChange={(e) => setUsername(e.target.value)} required /></Form.Group>
        <Form.Group className="mb-2"><Form.Label>Senha inicial</Form.Label><Form.Control type="password" minLength={5} maxLength={128} value={password} onChange={(e) => setPassword(e.target.value)} required /></Form.Group>
        <Form.Select value={role} onChange={(e) => setRole(e.target.value as UserRole)}><option value="user">Usuário</option><option value="admin">Administrador</option></Form.Select>
      </Modal.Body><Modal.Footer><Button variant="secondary" onClick={() => setShowCreate(false)}>Cancelar</Button><Button type="submit">Criar</Button></Modal.Footer>
    </Form></Modal>
    <Modal show={Boolean(resetUser)} onHide={() => setResetUser(null)}><Form onSubmit={reset}>
      <Modal.Header closeButton><Modal.Title>Redefinir senha</Modal.Title></Modal.Header><Modal.Body><Form.Control type="password" minLength={5} maxLength={128} value={resetPassword} onChange={(e) => setResetPassword(e.target.value)} required /></Modal.Body>
      <Modal.Footer><Button variant="secondary" onClick={() => setResetUser(null)}>Cancelar</Button><Button type="submit" variant="danger">Redefinir</Button></Modal.Footer>
    </Form></Modal>
  </>;
}
