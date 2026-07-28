import { Link } from "react-router-dom";

import { APP_NAME } from "../utils/app";

const CARDS = [
  {
    title: "Equipamentos",
    description: "Cadastro de equipamentos industriais.",
    to: "/cadastros/equipamentos",
    icon: "bi-gear",
  },
  {
    title: "Secoes",
    description: "Secoes vinculadas a cada equipamento.",
    to: "/cadastros/secoes",
    icon: "bi-diagram-3",
  },
  {
    title: "Tipos de Variavel",
    description: "Significado industrial das variaveis.",
    to: "/cadastros/tipos-variavel",
    icon: "bi-tags",
  },
  {
    title: "Tags PI",
    description: "Tags do PI Web API (somente administracao na Fase 1).",
    to: "/cadastros/tags-pi",
    icon: "bi-bookmark-star",
  },
];

export function DashboardPage() {
  return (
    <div data-testid="dashboard-page">
      <div className="page-header">
        <div>
          <h1 className="page-header__title">Painel inicial</h1>
          <p className="page-header__subtitle">
            Bem-vindo ao {APP_NAME}. Acesse os cadastros disponiveis na Fase 1.
          </p>
        </div>
      </div>
      <div className="row g-3">
        {CARDS.map((card) => (
          <div className="col-12 col-md-6 col-xl-3" key={card.to}>
            <Link to={card.to} className="text-decoration-none text-reset">
              <div className="card piad-card h-100">
                <div className="card-body">
                  <div className="d-flex align-items-center gap-3">
                    <span
                      className="d-inline-flex align-items-center justify-content-center rounded"
                      style={{ width: 44, height: 44, backgroundColor: "var(--piad-blue-light)", color: "var(--piad-blue)" }}
                    >
                      <i className={`bi ${card.icon} fs-4`} aria-hidden="true" />
                    </span>
                    <div>
                      <h5 className="mb-1">{card.title}</h5>
                      <p className="mb-0 text-muted small">{card.description}</p>
                    </div>
                  </div>
                </div>
              </div>
            </Link>
          </div>
        ))}
      </div>
      <div className="card piad-card mt-4">
        <div className="card-header">Sobre a Fase 1</div>
        <div className="card-body">
          <p className="mb-0">
            Esta fase implementa apenas os cadastros administrativos. A integracao com o PI Web API,
            validacao de tags, consulta de valores historicos, graficos, correlacao, estatistica
            descritiva e dashboards serao entregues nas proximas fases.
          </p>
        </div>
      </div>
    </div>
  );
}
