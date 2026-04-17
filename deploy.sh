#!/usr/bin/env bash
set -euo pipefail

# Deploy apcupsd-client via Helm with sops-encrypted secrets
# Usage: ./deploy.sh [install|upgrade|diff|destroy|status|logs|restart]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHART_DIR="${SCRIPT_DIR}/chart"
RELEASE="apcupsd-client"
NAMESPACE="apcupsd"
VALUES="${CHART_DIR}/values.yaml"
SECRETS="secrets://${CHART_DIR}/values-secret.yaml"
ACTION="${1:-upgrade}"

# Preflight checks
for cmd in helm sops; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "ERROR: $cmd not found in PATH" >&2
    exit 1
  fi
done

# Verify helm-secrets plugin is available
if ! helm plugin list | grep -q secrets; then
  echo "ERROR: helm-secrets plugin not installed. Install with: helm plugin install https://github.com/jkroepke/helm-secrets" >&2
  exit 1
fi

# Check if secrets file exists
if [[ ! -f "${CHART_DIR}/values-secret.yaml" ]]; then
  echo "ERROR: values-secret.yaml not found. Copy values-secret.yaml.example and encrypt with sops." >&2
  exit 1
fi

case "$ACTION" in
  install)
    echo "--- Installing ${RELEASE} ---"
    helm install "$RELEASE" "$CHART_DIR" \
      -n "$NAMESPACE" --create-namespace \
      -f "$VALUES" \
      -f "$SECRETS"
    echo "--- Install complete ---"
    kubectl -n "$NAMESPACE" get pods
    ;;

  upgrade)
    echo "--- Upgrading ${RELEASE} ---"
    helm upgrade "$RELEASE" "$CHART_DIR" \
      -n "$NAMESPACE" --create-namespace --install \
      -f "$VALUES" \
      -f "$SECRETS"
    echo "--- Upgrade complete ---"
    kubectl -n "$NAMESPACE" get pods
    ;;

  diff)
    if ! helm plugin list | grep -q diff; then
      echo "ERROR: helm-diff plugin not installed. Install with: helm plugin install https://github.com/databus23/helm-diff" >&2
      exit 1
    fi
    helm diff upgrade "$RELEASE" "$CHART_DIR" \
      -n "$NAMESPACE" \
      -f "$VALUES" \
      -f "$SECRETS" || true
    ;;

  template)
    helm template "$RELEASE" "$CHART_DIR" \
      -n "$NAMESPACE" \
      -f "$VALUES" \
      -f "$SECRETS"
    ;;

  destroy)
    echo "--- Uninstalling ${RELEASE} ---"
    helm uninstall "$RELEASE" -n "$NAMESPACE" --ignore-not-found
    echo "--- Destroyed ---"
    ;;

  status)
    kubectl -n "$NAMESPACE" get all
    ;;

  logs)
    kubectl -n "$NAMESPACE" logs -l app.kubernetes.io/name=apcupsd-client -f --tail=50
    ;;

  restart)
    kubectl -n "$NAMESPACE" rollout restart deployment/apcupsd-client
    kubectl -n "$NAMESPACE" rollout status deployment/apcupsd-client --timeout=120s
    ;;

  *)
    echo "Usage: $0 {install|upgrade|diff|template|destroy|status|logs|restart}" >&2
    exit 1
    ;;
esac
