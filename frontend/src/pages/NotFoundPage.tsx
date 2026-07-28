import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <div className="card piad-card">
      <div className="card-body text-center py-5">
        <i className="bi bi-compass fs-1 text-muted" aria-hidden="true" />
        <h2 className="mt-3">Pagina nao encontrada</h2>
        <p className="text-muted">A rota solicitada nao existe.</p>
        <Link to="/" className="btn btn-piad-primary">
          Voltar para o inicio
        </Link>
      </div>
    </div>
  );
}
