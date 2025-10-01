#!/bin/bash
# k8s/scripts/create-cluster.sh
# Create kind cluster with proper configuration

set -e  # Exit on error

CLUSTER_NAME="streemm"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
K8S_DIR="$(dirname "$SCRIPT_DIR")"

echo "Creating kind cluster: $CLUSTER_NAME"
echo ""

# Check if kind is available
if ! command -v kind &> /dev/null; then
    echo "ERROR: kind not found. Please install kind first:"
    echo "   brew install kind"
    exit 1
fi

# Check if cluster already exists
if kind get clusters 2>/dev/null | grep -q "^$CLUSTER_NAME$"; then
    echo "WARNING: Cluster '$CLUSTER_NAME' already exists."
    read -p "   Delete and recreate? (y/N) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Deleting existing cluster..."
        kind delete cluster --name "$CLUSTER_NAME"
        echo ""
    else
        echo "Using existing cluster"
        exit 0
    fi
fi

# Create cluster
echo "Creating cluster with configuration from k8s/kind/cluster-config.yaml"
kind create cluster --config "$K8S_DIR/kind/cluster-config.yaml"
echo ""

# Verify cluster
echo "Cluster created successfully!"
echo ""

# Show cluster info
echo "Cluster Info:"
kubectl cluster-info --context "kind-$CLUSTER_NAME"
echo ""

echo "Next steps:"
echo "   1. Deploy all resources: ./k8s/scripts/deploy-all.sh"
echo "   2. Watch deployment:     kubectl get pods -n streemm -w"
echo "   3. View logs:            ./k8s/scripts/logs.sh <service-name>"
