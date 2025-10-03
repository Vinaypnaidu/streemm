#!/bin/bash
# k8s/scripts/install-keda.sh
# Install KEDA (Kubernetes Event-Driven Autoscaling) via Helm

set -e  # Exit on error

KEDA_VERSION="2.14.0"
KEDA_NAMESPACE="keda"

echo "Installing KEDA v${KEDA_VERSION}..."
echo ""

# Check if helm is installed
if ! command -v helm &> /dev/null; then
    echo "ERROR: Helm not found. Please install Helm first:"
    echo ""
    echo "   macOS:  brew install helm"
    echo "   Linux:  curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash"
    echo ""
    exit 1
fi

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    echo "ERROR: kubectl not found. Cannot install KEDA without kubectl."
    exit 1
fi

# Check if cluster is running
if ! kubectl cluster-info &> /dev/null; then
    echo "ERROR: No Kubernetes cluster found. Please create a cluster first."
    exit 1
fi

# Check if KEDA is already installed
if kubectl get namespace "$KEDA_NAMESPACE" &> /dev/null; then
    echo "KEDA namespace already exists. Checking installation..."
    if kubectl get deployment keda-operator -n "$KEDA_NAMESPACE" &> /dev/null 2>&1; then
        echo "   KEDA is already installed!"
        echo ""
        kubectl get pods -n "$KEDA_NAMESPACE"
        echo ""
        echo "To reinstall, first run: helm uninstall keda -n $KEDA_NAMESPACE"
        exit 0
    fi
fi

# Add KEDA Helm repository
echo "Adding KEDA Helm repository..."
helm repo add kedacore https://kedacore.github.io/charts
helm repo update
echo "   Repository added"
echo ""

# Install KEDA
echo "Installing KEDA via Helm..."
helm install keda kedacore/keda \
    --namespace "$KEDA_NAMESPACE" \
    --create-namespace \
    --version "$KEDA_VERSION" \
    --wait \
    --timeout 5m
echo "   KEDA installed"
echo ""

# Verify installation
echo "Verifying KEDA installation..."
echo ""

# Wait for KEDA operator to be ready
echo "Waiting for KEDA operator to be ready..."
kubectl wait --for=condition=ready pod \
    -l app.kubernetes.io/name=keda-operator \
    -n "$KEDA_NAMESPACE" \
    --timeout=120s

# Wait for KEDA metrics server to be ready
echo "Waiting for KEDA metrics server to be ready..."
kubectl wait --for=condition=ready pod \
    -l app.kubernetes.io/name=keda-operator-metrics-apiserver \
    -n "$KEDA_NAMESPACE" \
    --timeout=120s

echo ""
echo "KEDA installed successfully!"
echo ""

# Show KEDA components
echo "KEDA Components:"
kubectl get pods -n "$KEDA_NAMESPACE"
echo ""

echo "KEDA is now ready to use!"