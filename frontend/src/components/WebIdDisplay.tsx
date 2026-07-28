import { useState } from "react";

interface WebIdDisplayProps {
  webId: string | null;
}

function truncateWebId(value: string, max = 16): string {
  if (value.length <= max) {
    return value;
  }
  const side = Math.floor((max - 1) / 2);
  return `${value.slice(0, side)}...${value.slice(-side)}`;
}

export function WebIdDisplay({ webId }: WebIdDisplayProps) {
  const [copied, setCopied] = useState(false);
  if (!webId) {
    return <span className="text-muted small">-</span>;
  }
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(webId);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };
  return (
    <span className="d-inline-flex align-items-center gap-2">
      <code title={webId} data-testid="pi-webid">
        {truncateWebId(webId)}
      </code>
      <button
        type="button"
        className="btn btn-link btn-sm p-0"
        onClick={handleCopy}
        title="Copiar WebId"
      >
        <i className="bi bi-clipboard" />
      </button>
      {copied ? <span className="text-success small">copiado</span> : null}
    </span>
  );
}
