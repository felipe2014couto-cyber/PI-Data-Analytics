import { Alert } from "react-bootstrap";

interface FeedbackAlertProps {
  variant: "success" | "info" | "warning" | "danger";
  message: string;
}

export function FeedbackAlert({ variant, message }: FeedbackAlertProps) {
  if (!message) {
    return null;
  }
  return (
    <Alert variant={variant} className="mb-3 py-2">
      {message}
    </Alert>
  );
}
