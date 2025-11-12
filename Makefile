.PHONY: help install test demo clean deps check

help:
	@echo "VPC Management Tool - Make targets:"
	@echo "  make deps      - Install system dependencies"
	@echo "  make check     - Check prerequisites"
	@echo "  make install   - Install vpcctl to /usr/local/bin"
	@echo "  make demo      - Run full demonstration"
	@echo "  make test      - Run connectivity tests"
	@echo "  make clean     - Clean up all VPCs and resources"
	@echo "  make uninstall - Remove vpcctl from system"

deps:
	@echo "Installing dependencies..."
	@if command -v apt-get > /dev/null; then \
		sudo apt-get update && \
		sudo apt-get install -y python3 iproute2 iptables bridge-utils curl; \
	elif command -v yum > /dev/null; then \
		sudo yum install -y python3 iproute iptables bridge-utils curl; \
	else \
		echo "Unsupported package manager. Please install manually:"; \
		echo "  - python3"; \
		echo "  - iproute2"; \
		echo "  - iptables"; \
		echo "  - bridge-utils"; \
		exit 1; \
	fi
	@echo "Dependencies installed successfully!"

check:
	@echo "Checking prerequisites..."
	@command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 not found"; exit 1; }
	@command -v ip >/dev/null 2>&1 || { echo "ERROR: ip command not found"; exit 1; }
	@command -v iptables >/dev/null 2>&1 || { echo "ERROR: iptables not found"; exit 1; }
	@command -v bridge >/dev/null 2>&1 || { echo "ERROR: bridge command not found"; exit 1; }
	@if [ $$(id -u) -ne 0 ]; then \
		echo "WARNING: Not running as root. Use 'sudo make' for most targets."; \
	fi
	@echo "All prerequisites met!"

install: check
	@echo "Installing vpcctl..."
	chmod +x vpcctl.py
	sudo cp vpcctl.py /usr/local/bin/vpcctl
	@echo "vpcctl installed to /usr/local/bin/vpcctl"
	@echo "You can now run: sudo vpcctl <command>"

uninstall:
	@echo "Removing vpcctl..."
	sudo rm -f /usr/local/bin/vpcctl
	@echo "vpcctl uninstalled"

demo: check
	@echo "Running full VPC demonstration..."
	@if [ ! -f test_demo.sh ]; then \
		echo "ERROR: test_demo.sh not found"; \
		exit 1; \
	fi
	chmod +x test_demo.sh
	sudo ./test_demo.sh

test: check
	@echo "Running connectivity tests..."
	@echo ""
	@echo "=== Creating test VPC ==="
	sudo ./vpcctl.py create-vpc test-vpc 10.100.0.0/16
	sudo ./vpcctl.py add-subnet test-vpc public 10.100.1.0/24 --type public
	sudo ./vpcctl.py add-subnet test-vpc private 10.100.2.0/24 --type private
	@echo ""
	@echo "=== Testing inter-subnet connectivity ==="
	@sudo ip netns exec test-vpc-private ping -c 3 10.100.1.1 && echo "✓ Private → Public: OK" || echo "✗ Private → Public: FAILED"
	@echo ""
	@echo "=== Testing NAT (may fail if no internet) ==="
	@sudo ip netns exec test-vpc-public ping -c 2 -W 2 8.8.8.8 && echo "✓ Public → Internet: OK" || echo "✗ Public → Internet: FAILED (check internet_interface)"
	@echo ""
	@echo "=== Cleaning up test VPC ==="
	sudo ./vpcctl.py delete-vpc test-vpc
	@echo ""
	@echo "Tests complete!"

clean:
	@echo "Cleaning up all VPCs..."
	@if [ -f ~/.vpcctl/vpcs.json ]; then \
		VPC_NAMES=$$(sudo ./vpcctl.py list 2>/dev/null | grep "VPC:" | awk '{print $$2}'); \
		for vpc in $$VPC_NAMES; do \
			echo "Deleting VPC: $$vpc"; \
			sudo ./vpcctl.py delete-vpc $$vpc 2>/dev/null || true; \
		done; \
	fi
	@echo "Removing state files..."
	@rm -rf ~/.vpcctl
	@echo "Cleanup complete!"

example-basic:
	@echo "Creating basic VPC example..."
	sudo ./vpcctl.py create-vpc example 10.0.0.0/16
	sudo ./vpcctl.py add-subnet example web 10.0.1.0/24 --type public
	sudo ./vpcctl.py add-subnet example db 10.0.2.0/24 --type private
	sudo ./vpcctl.py list
	@echo ""
	@echo "Example VPC created! Test with:"
	@echo "  sudo ip netns exec example-web ping 10.0.2.1"
	@echo ""
	@echo "Clean up with:"
	@echo "  sudo ./vpcctl.py delete-vpc example"

example-peering:
	@echo "Creating VPC peering example..."
	sudo ./vpcctl.py create-vpc vpc-east 10.0.0.0/16
	sudo ./vpcctl.py add-subnet vpc-east app 10.0.1.0/24 --type public
	sudo ./vpcctl.py create-vpc vpc-west 172.16.0.0/16
	sudo ./vpcctl.py add-subnet vpc-west service 172.16.1.0/24 --type public
	@echo ""
	@echo "Testing isolation (should fail)..."
	@sudo ip netns exec vpc-east-app ping -c 2 -W 1 172.16.1.1 && echo "✗ VPCs not isolated!" || echo "✓ VPCs isolated"
	@echo ""
	@echo "Enabling peering..."
	sudo ./vpcctl.py peer vpc-east vpc-west
	@echo ""
	@echo "Testing cross-VPC connectivity..."
	@sudo ip netns exec vpc-east-app ping -c 2 172.16.1.1 && echo "✓ Peering works!" || echo "✗ Peering failed"
	@echo ""
	@echo "Clean up with:"
	@echo "  sudo ./vpcctl.py delete-vpc vpc-east"
	@echo "  sudo ./vpcctl.py delete-vpc vpc-west"

example-firewall:
	@echo "Creating firewall example..."
	sudo ./vpcctl.py create-vpc fw-demo 10.0.0.0/16
	sudo ./vpcctl.py add-subnet fw-demo public 10.0.1.0/24 --type public
	@echo '{"subnet": "10.0.1.0/24", "ingress": [{"port": 80, "protocol": "tcp", "action": "allow"}, {"port": 22, "protocol": "tcp", "action": "deny"}]}' > /tmp/fw-policy.json
	sudo ./vpcctl.py apply-firewall fw-demo public /tmp/fw-policy.json
	@echo ""
	@echo "Firewall rules applied!"
	@echo "View rules with:"
	@echo "  sudo ip netns exec fw-demo-public iptables -L -n -v"
	@echo ""
	@echo "Clean up with:"
	@echo "  sudo ./vpcctl.py delete-vpc fw-demo"

list:
	@sudo ./vpcctl.py list

status:
	@echo "=== VPC Status ==="
	@echo ""
	@echo "Active VPCs:"
	@sudo ./vpcctl.py list 2>/dev/null || echo "No VPCs found"
	@echo ""
	@echo "Network Namespaces:"
	@sudo ip netns list 2>/dev/null || echo "None"
	@echo ""
	@echo "Bridges:"
	@ip link show type bridge 2>/dev/null | grep "^[0-9]" || echo "None"
	@echo ""
	@echo "NAT Rules:"
	@sudo iptables -t nat -L POSTROUTING -n | grep -E "MASQUERADE|anywhere" || echo "None"
