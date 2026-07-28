import { FormEvent, useState } from "react";
import { Alert, Button, Card, Form } from "react-bootstrap";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export function LoginPage() {
  const { user, login } = useAuth(); const navigate = useNavigate(); const location = useLocation();
  const [username, setUsername] = useState(""); const [password, setPassword] = useState(""); const [error, setError] = useState<string | null>(null); const [loading, setLoading] = useState(false);
  if (user) return <Navigate to={user.must_change_password ? "/trocar-senha" : "/"} replace />;
  const submit = async (event: FormEvent) => { event.preventDefault(); setLoading(true); setError(null); try { const authenticated = await login(username, password); navigate(authenticated.must_change_password ? "/trocar-senha" : ((location.state as { from?: string } | null)?.from ?? "/"), { replace: true }); } catch { setError("Credenciais inválidas ou acesso indisponível."); } finally { setLoading(false); } };
  return <div className="min-vh-100 d-flex align-items-center justify-content-center bg-light"><Card style={{ width: 380 }}><Card.Body><h1 className="h4 mb-3">PI Analytics Data</h1>{error ? <Alert variant="danger" role="alert">{error}</Alert> : null}<Form onSubmit={submit}><Form.Group className="mb-3"><Form.Label>Usuário</Form.Label><Form.Control data-testid="login-username" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required /></Form.Group><Form.Group className="mb-3"><Form.Label>Senha</Form.Label><Form.Control data-testid="login-password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></Form.Group><Button data-testid="login-submit" type="submit" disabled={loading} className="w-100">Entrar</Button></Form></Card.Body></Card></div>;
}
