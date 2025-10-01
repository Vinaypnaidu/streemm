# Makefile for Streemm Kubernetes operations

.PHONY: help cluster deploy destroy clean

# Default target
help:
	@echo "Streemm Kubernetes Commands"
	@echo ""
	@echo "Cluster Management:"
	@echo "  make cluster        Create kind cluster"
	@echo "  make clean          Delete kind cluster"
	@echo ""
	@echo "Deployment:"
	@echo "  make deploy         Deploy all resources"
	@echo "  make destroy        Delete all resources"
	@echo ""
	@echo "Development:"
	@echo "  make restart        Restart a service (use SERVICE=api)"
	@echo ""
	@echo "Quick Start:"
	@echo "  make cluster && make deploy"
	@echo ""

# Create kind cluster
cluster:
	@./k8s/scripts/create-cluster.sh

# Deploy all resources
deploy:
	@./k8s/scripts/deploy-all.sh

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
	@kubectl rollout restart deployment/$(SERVICE) -n streemm
	@echo "$(SERVICE) restarted"

# Delete cluster completely
clean:
	@echo "Deleting kind cluster: streemm"
	@kind delete cluster --name streemm
	@echo "Cluster deleted"

# Quick start (create cluster + deploy)
quickstart: cluster deploy
	@echo ""
	@echo "Quickstart complete!"
	@echo ""
	@echo "Run 'make status' to check deployment progress"

# Watch pods
watch:
	@kubectl get pods -n streemm -w
