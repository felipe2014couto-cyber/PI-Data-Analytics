import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  handleGoHome = () => {
    this.setState({ hasError: false, error: null });
    window.location.href = "/";
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }
      return (
        <div className="container py-5">
          <div className="card piad-card">
            <div className="card-body text-center">
              <i className="bi bi-exclamation-triangle fs-1 text-warning mb-3" aria-hidden="true" />
              <h2 className="mb-3">Algo deu errado</h2>
              <p className="text-muted mb-4">
                Ocorreu um erro inesperado ao carregar esta pagina. Por favor, tente novamente.
              </p>
              {this.state.error && (
                <details className="mb-4">
                  <summary className="text-muted">Detalhes do erro</summary>
                  <pre className="text-start small text-muted mt-2 p-3 bg-light rounded">
                    {this.state.error.message}
                  </pre>
                </details>
              )}
              <div className="d-flex justify-content-center gap-3">
                <button
                  className="btn btn-piad-primary"
                  onClick={this.handleReset}
                  type="button"
                >
                  <i className="bi bi-arrow-clockwise me-1" />
                  Tentar novamente
                </button>
                <button
                  className="btn btn-outline-secondary"
                  onClick={this.handleGoHome}
                  type="button"
                >
                  <i className="bi bi-house me-1" />
                  Voltar ao inicio
                </button>
              </div>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
