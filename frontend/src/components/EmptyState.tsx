import type { ReactNode } from "react";

interface EmptyStateProps {
  icon?: string;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
}

export function EmptyState({ icon = "bi-inbox", title, description, action }: EmptyStateProps) {
  return (
    <div className="piad-empty">
      <i className={`bi ${icon}`} aria-hidden="true" />
      <h5 className="mt-3 mb-1">{title}</h5>
      {description ? <p className="mb-3">{description}</p> : null}
      {action}
    </div>
  );
}
