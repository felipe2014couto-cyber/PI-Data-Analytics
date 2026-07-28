import { useEffect, useState, type ReactNode } from "react";
import { Modal, Button } from "react-bootstrap";

interface ConfirmModalProps {
  show: boolean;
  title: string;
  message: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: "danger" | "primary";
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmModal(props: ConfirmModalProps) {
  const {
    show,
    title,
    message,
    confirmLabel = "Excluir",
    cancelLabel = "Cancelar",
    variant = "danger",
    busy = false,
    onConfirm,
    onCancel,
  } = props;

  const [internalBusy, setInternalBusy] = useState(false);

  useEffect(() => {
    if (!show) {
      setInternalBusy(false);
    }
  }, [show]);

  const isBusy = busy || internalBusy;

  const handleConfirm = async () => {
    try {
      setInternalBusy(true);
      await Promise.resolve(onConfirm());
    } finally {
      setInternalBusy(false);
    }
  };

  return (
    <Modal show={show} onHide={onCancel} centered backdrop="static">
      <Modal.Header closeButton={!isBusy}>
        <Modal.Title>{title}</Modal.Title>
      </Modal.Header>
      <Modal.Body>{message}</Modal.Body>
      <Modal.Footer>
        <Button variant="outline-secondary" onClick={onCancel} disabled={isBusy}>
          {cancelLabel}
        </Button>
        <Button variant={variant} onClick={handleConfirm} disabled={isBusy}>
          {isBusy ? "Processando..." : confirmLabel}
        </Button>
      </Modal.Footer>
    </Modal>
  );
}
