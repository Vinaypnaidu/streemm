# Makefile for easy k8s operations

.PHONY: help cluster deploy deploy-with-autoscaling install-keda destroy clean

# Default target
help:
	@echo "Streem Kubernetes Commands"
	@echo ""
	@echo "Cluster Management:"
	@echo "  make cluster                  Create kind cluster"
	@echo "  make clean                    Delete kind cluster"
	@echo ""
	@echo "Deployment:"
	@echo "  make deploy                   Deploy all resources (standard)"
	@echo "  make deploy-with-autoscaling  Deploy with KEDA worker autoscaling"
	@echo "  make destroy                  Delete all resources"
	@echo ""
	@echo "KEDA Autoscaling:"
	@echo "  make install-keda             Install KEDA for autoscaling"
	@echo "  make monitor-autoscaling      Monitor worker autoscaling"
	@echo ""
	@echo "Development:"
	@echo "  make restart                  Restart a service (use SERVICE=api)"
	@echo "  make watch                    Watch all pods"
	@echo ""
	@echo "Quick Start:"
	@echo "  make cluster && make deploy"
	@echo "  make cluster && make install-keda && make deploy-with-autoscaling"
	@echo ""

# Create kind cluster
cluster:
	@./k8s/scripts/create-cluster.sh

# Deploy all resources (standard)
deploy:
	@./k8s/scripts/deploy-all.sh

# Deploy with KEDA autoscaling
deploy-with-autoscaling:
	@./k8s/scripts/deploy-with-autoscaling.sh

# Install KEDA
install-keda:
	@./k8s/scripts/install-keda.sh

# Monitor autoscaling
monitor-autoscaling:
	@./k8s/scripts/monitor-autoscaling.sh

# Delete all resources (keep cluster)
destroy:
	@./k8s/scripts/destroy-all.sh

# Restart a service (use: make restart SERVICE=api)
restart:
	@if [ -z "$(SERVICE)" ]; then \
		echo "ERROR: Please specify a service: make restart SERVICE=api"; \
		exit 1; \
	fi
	@echo "Restarting $(SERVICE)..."
	@kubectl rollout restart deployment/$(SERVICE) -n streem
	@echo "$(SERVICE) restarted"

# Delete cluster completely
clean:
	@echo "Deleting kind cluster: streem"
	@kind delete cluster --name streem
	@echo "Cluster deleted"

# Quick start (create cluster + deploy)
quickstart: cluster deploy
	@echo ""
	@echo "Quickstart complete!"
	@echo ""
	@echo "Run 'make watch' to check deployment progress"

# Quick start with autoscaling
quickstart-autoscaling: cluster install-keda deploy-with-autoscaling
	@echo ""
	@echo "Quickstart with autoscaling complete!"
	@echo ""
	@echo "Run 'make monitor-autoscaling' to watch autoscaling behavior"

# Watch pods
watch:
	@kubectl get pods -n streem -w
