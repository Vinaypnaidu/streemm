#!/bin/bash
# k8s/scripts/monitor-autoscaling.sh
# Monitor KEDA autoscaling behavior in real-time

NAMESPACE="streemm"

echo "════════════════════════════════════════════════════════════"
echo "KEDA Worker Autoscaling Monitor"
echo "════════════════════════════════════════════════════════════"
echo ""

# Check if KEDA is installed
if ! kubectl get namespace keda &> /dev/null; then
    echo "ERROR: KEDA is not installed."
    exit 1
fi

# Check if ScaledObject exists
if ! kubectl get scaledobject worker-scaler -n "$NAMESPACE" &> /dev/null 2>&1; then
    echo "ERROR: worker-scaler ScaledObject not found in namespace '$NAMESPACE'"
    echo ""
    echo "Deploy with autoscaling first:"
    echo "   ./k8s/scripts/deploy-with-autoscaling.sh"
    exit 1
fi

echo "Monitoring autoscaling behavior..."
echo "Press Ctrl+C to stop"
echo ""

# get queue length
get_queue_length() {
    kubectl exec -n "$NAMESPACE" deployment/api -c api -- \
        bash -c "cd /app && python3 -c 'from cache import redis_client; print(redis_client.llen(\"q:videos\"))'" 2>/dev/null || echo "?"
}

# get worker pod count
get_worker_count() {
    kubectl get pods -n "$NAMESPACE" -l app=worker --no-headers 2>/dev/null | wc -l | tr -d ' '
}

# get ScaledObject info
get_scaled_info() {
    kubectl get scaledobject worker-scaler -n "$NAMESPACE" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "Unknown"
}

# Monitoring loop
echo "$(date +'%H:%M:%S') | Queue | Workers | ScaledObject | Status"
echo "─────────────────────────────────────────────────────────────"

while true; do
    TIMESTAMP=$(date +'%H:%M:%S')
    QUEUE_LEN=$(get_queue_length)
    WORKER_COUNT=$(get_worker_count)
    SCALED_STATUS=$(get_scaled_info)
    
    # Get worker pod status
    WORKER_STATUS=$(kubectl get pods -n "$NAMESPACE" -l app=worker --no-headers 2>/dev/null | awk '{print $3}' | sort | uniq -c | tr '\n' ' ' || echo "No workers")
    
    printf "%s | %-5s | %-7s | %-12s | %s\n" "$TIMESTAMP" "$QUEUE_LEN" "$WORKER_COUNT" "$SCALED_STATUS" "$WORKER_STATUS"
    
    sleep 5
done
