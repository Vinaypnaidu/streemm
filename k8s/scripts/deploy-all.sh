#!/bin/bash
# k8s/scripts/deploy-all.sh
# Deploy all Kubernetes resources in the correct order

set -e  # Exit on error

NAMESPACE="streem"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
K8S_DIR="$(dirname "$SCRIPT_DIR")"

echo "Deploying Streem to Kubernetes..."
echo ""

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    echo "ERROR: kubectl not found. Please install kubectl first."
    exit 1
fi

# Check if cluster is running
if ! kubectl cluster-info &> /dev/null; then
    echo "ERROR: No Kubernetes cluster found. Please create a kind cluster first:"
    echo "   kind create cluster --config k8s/kind/cluster-config.yaml"
    exit 1
fi

# Create namespace if it doesn't exist
if ! kubectl get namespace "$NAMESPACE" &> /dev/null; then
    echo "Creating namespace: $NAMESPACE"
    kubectl create namespace "$NAMESPACE"
    echo ""
fi

# Set namespace as default
echo "Setting default namespace to: $NAMESPACE"
kubectl config set-context --current --namespace="$NAMESPACE"
echo ""

# Deploy stateful services (infrastructure)
echo "Deploying stateful services..."
kubectl apply -f "$K8S_DIR/stateful/postgres.yaml"
kubectl apply -f "$K8S_DIR/stateful/redis.yaml"
kubectl apply -f "$K8S_DIR/stateful/minio.yaml"
kubectl apply -f "$K8S_DIR/stateful/opensearch.yaml"
kubectl apply -f "$K8S_DIR/stateful/neo4j.yaml"
kubectl apply -f "$K8S_DIR/stateful/mailpit.yaml"
echo "   Stateful services deployed"
echo ""

# Wait for stateful services to be ready
echo "Waiting for stateful services to be ready..."
kubectl wait --for=condition=ready pod -l app=postgres --timeout=120s -n "$NAMESPACE" 2>/dev/null || true
kubectl wait --for=condition=ready pod -l app=redis --timeout=120s -n "$NAMESPACE" 2>/dev/null || true
kubectl wait --for=condition=ready pod -l app=minio --timeout=120s -n "$NAMESPACE" 2>/dev/null || true
kubectl wait --for=condition=ready pod -l app=neo4j --timeout=180s -n "$NAMESPACE" 2>/dev/null || true
kubectl wait --for=condition=ready pod -l app=mailpit --timeout=120s -n "$NAMESPACE" 2>/dev/null || true
echo "   Infrastructure services ready"
echo ""

# Deploy configuration
echo "Deploying configuration..."
kubectl apply -f "$K8S_DIR/config/secrets.yaml"
kubectl apply -f "$K8S_DIR/config/configmap.yaml"
echo "   Configuration deployed"
echo ""

# Deploy application services
echo "Deploying application services..."
kubectl apply -f "$K8S_DIR/app/api.yaml"
kubectl apply -f "$K8S_DIR/app/worker.yaml"
kubectl apply -f "$K8S_DIR/app/notifier.yaml"
kubectl apply -f "$K8S_DIR/app/web.yaml"
echo "   Application services deployed"
echo ""

# Show status
echo "Deployment Status:"
echo ""
kubectl get pods -n "$NAMESPACE"
echo ""

echo "Deployment complete!"
echo ""
echo "Next steps:"
echo "   1. Watch pods come up: kubectl get pods -n $NAMESPACE -w"
echo "   2. Check pods status and logs: k9s -n $NAMESPACE"
echo "   3. Access services:"
echo "      - Web:           http://localhost:3000"
echo "      - API:           http://localhost:8000"
echo "      - MinIO Console: http://localhost:9001"
echo "      - Mailpit:       http://localhost:8025"
echo "      - Neo4j Browser: http://localhost:30474"
echo ""
echo "NOTE: First startup takes 3-5 minutes (installing dependencies)"
