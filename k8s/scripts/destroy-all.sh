#!/bin/bash
# k8s/scripts/destroy-all.sh
# Clean up all Kubernetes resources

set -e  # Exit on error

NAMESPACE="streemm"

echo "Destroying Streemm Kubernetes resources..."
echo ""

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    echo "ERROR: kubectl not found. Please install kubectl first."
    exit 1
fi

# Check if namespace exists
if ! kubectl get namespace "$NAMESPACE" &> /dev/null; then
    echo "Namespace '$NAMESPACE' doesn't exist. Nothing to destroy."
    exit 0
fi

# Confirm deletion
read -p "WARNING: This will DELETE all resources in namespace '$NAMESPACE'. Continue? (y/N) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

echo ""
echo "Deleting namespace (this will delete all resources)..."
kubectl delete namespace "$NAMESPACE"
echo "   Namespace and all resources deleted"
echo ""

echo "Cleanup complete!"
echo ""
echo "To delete the entire cluster:"
echo "   kind delete cluster --name streemm"