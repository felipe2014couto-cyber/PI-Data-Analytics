import { FormEvent, useState } from "react";
import { Alert, Button, Card, Form } from "react-bootstrap";
import { Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export function RequiredPasswordChangePage() {
  const { user, loading, changePassword, logout } = useAuth(); const navigate = useNavigate();
  const [currentPassword, setCurrentPassword] = useState(""); const [newPassword, setNewPassword] = useState(""); const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState<string | null>(null); const [saving, setSaving] = useState(false);
  if (loading) return <div className="p-4">Verificando sessão...</div>;
  if (!user) return <Navigate to="/login" replace />;
  if (!user.must_change_password) return <Navigate to="/" replace />;
  const submit = async (event: FormEvent) => { event.preventDefault(); setError(null); if (newPassword !== confirmation) { setError("A confirmação da nova senha não confere."); return; } setSaving(true); try { await changePassword(currentPassword, newPassword); navigate("/", { replace: true }); } catch { setError("Não foi possível alterar a senha. Confirme a senha atual e tente novamente."); } finally { setSaving(false); } };
  return <div className="min-vh-100 d-flex align-items-center justify-content-center bg-light"><Card style={{ width: 440 }}><Card.Body><h1 className="h4">Troca obrigatória de senha</h1><p>Altere sua senha para continuar usando a aplicação.</p>{error ? <Alert variant="danger">{error}</Alert> : null}<Form onSubmit={submit}>
    <Form.Group className="mb-2"><Form.Label>Senha atual</Form.Label><Form.Control data-testid="required-current-password" type="password" required value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} /></Form.Group>
    <Form.Group className="mb-2"><Form.Label>Nova senha</Form.Label><Form.Control data-testid="required-new-password" type="password" minLength={5} maxLength={128} required value={newPassword} onChange={(e) => setNewPassword(e.target.value)} /></Form.Group>
    <Form.Group className="mb-3"><Form.Label>Confirmar nova senha</Form.Label><Form.Control data-testid="required-confirm-password" type="password" minLength={5} maxLength={128} required value={confirmation} onChange={(e) => setConfirmation(e.target.value)} /></Form.Group>
    <div className="d-flex gap-2"><Button type="submit" disabled={saving}>Alterar senha</Button><Button type="button" variant="outline-danger" onClick={() => void logout()}>Sair</Button></div>
  </Form></Card.Body></Card></div>;
}
