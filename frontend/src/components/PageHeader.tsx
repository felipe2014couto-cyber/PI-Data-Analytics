import type { ReactNode } from "react";

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  center?: ReactNode;
  actions?: ReactNode;
}

export function PageHeader({ title, subtitle, center, actions }: PageHeaderProps) {
  return (
    <div className="page-header">
      <div>
        <h1 className="page-header__title">{title}</h1>
        {subtitle ? <p className="page-header__subtitle">{subtitle}</p> : null}
      </div>
      {center ? <div className="page-header__center">{center}</div> : null}
      {actions ? <div className="page-header__actions">{actions}</div> : null}
    </div>
  );
}
