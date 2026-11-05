#!/usr/bin/env bash
set -e

SERVICES=(
  "pi-analytics-backend.service"
  "pi-analytics-frontend.service"
  "pi-analytics-ingestion-staging.service"
)

ACTION="${1:-status}"

case "$ACTION" in
  start)
    echo "Iniciando serviços do PI Analytics..."
    systemctl --user start "${SERVICES[@]}"
    systemctl --user status "${SERVICES[@]}" --no-pager
    ;;
  stop)
    echo "Parando serviços do PI Analytics..."
    systemctl --user stop "${SERVICES[@]}"
    ;;
  restart)
    echo "Reiniciando serviços do PI Analytics..."
    systemctl --user restart "${SERVICES[@]}"
    systemctl --user status "${SERVICES[@]}" --no-pager
    ;;
  status)
    echo "=== Status dos Serviços do PI Analytics ==="
    systemctl --user status "${SERVICES[@]}" --no-pager
    ;;
  logs)
    SERVICE="${2:-backend}"
    if [ "$SERVICE" = "backend" ]; then
      journalctl --user -u pi-analytics-backend.service -f -n 50
    elif [ "$SERVICE" = "frontend" ]; then
      journalctl --user -u pi-analytics-frontend.service -f -n 50
    elif [ "$SERVICE" = "ingestion" ]; then
      journalctl --user -u pi-analytics-ingestion-staging.service -f -n 50
    else
      journalctl --user -u "${SERVICE}" -f -n 50
    fi
    ;;
  *)
    echo "Uso: $0 {start|stop|restart|status|logs [backend|frontend|ingestion]}"
    exit 1
    ;;
esac
