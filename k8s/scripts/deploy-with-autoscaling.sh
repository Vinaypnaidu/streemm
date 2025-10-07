#!/bin/bash
# k8s/scripts/deploy-with-autoscaling.sh
# Deploy all Kubernetes resources with KEDA autoscaling for workers

set -e  # Exit on error

NAMESPACE="streem"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
K8S_DIR="$(dirname "$SCRIPT_DIR")"

echo "Deploying Streem with KEDA Autoscaling..."
echo ""

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    echo "ERROR: kubectl not found. Please install kubectl first."
    exit 1
fi

# Check if cluster is running
if ! kubectl cluster-info &> /dev/null; then
    echo "ERROR: No Kubernetes cluster found. Please create a kind cluster first:"
    echo "   ./k8s/scripts/create-cluster.sh"
    exit 1
fi

# Check if KEDA is installed
echo "Checking for KEDA installation..."
if ! kubectl get namespace keda &> /dev/null; then
    echo ""
    echo "ERROR: KEDA is not installed. Autoscaling requires KEDA."
    echo ""
    echo "Aborting. Please install KEDA first:"
    echo "   ./k8s/scripts/install-keda.sh"
    exit 1
fi

# Verify KEDA operator is running
if ! kubectl get deployment keda-operator -n keda &> /dev/null; then
    echo ""
    echo "ERROR: KEDA operator not found. Please reinstall KEDA:"
    echo "   ./k8s/scripts/install-keda.sh"
    exit 1
fi

echo ""

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
kubectl apply -f "$K8S_DIR/stateful/mailpit.yaml"
echo "   Stateful services deployed"
echo ""

# Wait for stateful services to be ready
echo "Waiting for stateful services to be ready..."
kubectl wait --for=condition=ready pod -l app=postgres --timeout=120s -n "$NAMESPACE" 2>/dev/null || true
kubectl wait --for=condition=ready pod -l app=redis --timeout=120s -n "$NAMESPACE" 2>/dev/null || true
kubectl wait --for=condition=ready pod -l app=minio --timeout=120s -n "$NAMESPACE" 2>/dev/null || true
kubectl wait --for=condition=ready pod -l app=mailpit --timeout=120s -n "$NAMESPACE" 2>/dev/null || true
echo "   Infrastructure services ready"
echo ""

# Deploy configuration
echo "Deploying configuration..."
kubectl apply -f "$K8S_DIR/config/secrets.yaml"
kubectl apply -f "$K8S_DIR/config/configmap.yaml"
echo "   Configuration deployed"
echo ""

# Deploy application services (with autoscaled worker)
echo "Deploying application services..."
kubectl apply -f "$K8S_DIR/app/api.yaml"
kubectl apply -f "$K8S_DIR/app/worker-autoscaled.yaml"
kubectl apply -f "$K8S_DIR/app/notifier.yaml"
kubectl apply -f "$K8S_DIR/app/web.yaml"
echo "   Application services deployed"
echo ""

# Show status
echo "════════════════════════════════════════════════════════════"
echo "Deployment Status:"
echo ""
kubectl get pods -n "$NAMESPACE"
echo ""

# Show KEDA ScaledObject status
echo "KEDA Autoscaling Status:"
echo ""
kubectl get scaledobjects -n "$NAMESPACE"
echo ""

echo "════════════════════════════════════════════════════════════"
echo ""
echo "Deployment complete!"
echo ""
echo "Next steps:"
echo "   1. Monitor with k9s:     k9s -n $NAMESPACE"
echo ""
echo "Access services:"
echo "   - Web:           http://localhost:3000"
echo "   - API:           http://localhost:8000"
echo "   - MinIO Console: http://localhost:9001"
echo "   - Mailpit:       http://localhost:8025"
echo ""
echo "Monitor autoscaling:"
echo "   - Watch dashboard:  ./k8s/scripts/monitor-autoscaling.sh"
echo "   - Check queue:      kubectl exec -it deployment/api -n $NAMESPACE -c api -- bash -c 'cd /app && python3 -c \"from cache import redis_client; print(redis_client.llen(\\\"q:videos\\\"))\"'"
echo "   - Watch workers:    kubectl get pods -l app=worker -n $NAMESPACE -w"
echo "   - KEDA events:      kubectl describe scaledobject worker-scaler -n $NAMESPACE"
echo ""
echo "NOTE: First startup takes 3-5 minutes (installing dependencies)"
