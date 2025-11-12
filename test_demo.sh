#!/bin/bash
# Demo script showing VPC functionality

set -e

echo "=== VPC Networking Demo ==="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_test() {
    echo -e "${BLUE}[TEST]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

log_error() {
    echo -e "${RED}[✗]${NC} $1"
}

# Detect internet interface
IFACE=$(ip route | grep default | awk '{print $5}')
echo "Using internet interface: $IFACE"
echo ""

# Cleanup function
cleanup() {
    echo ""
    echo "=== Cleanup ==="
    sudo ./vpcctl.py delete-vpc vpc1 2>/dev/null || true
    sudo ./vpcctl.py delete-vpc vpc2 2>/dev/null || true
}

trap cleanup EXIT

# Step 1: Create VPC1
log_test "Creating VPC1 with CIDR 10.0.0.0/16"
sudo ./vpcctl.py create-vpc vpc1 10.0.0.0/16 --interface $IFACE
log_success "VPC1 created"
echo ""

# Step 2: Add public subnet to VPC1
log_test "Adding public subnet to VPC1"
sudo ./vpcctl.py add-subnet vpc1 pub 10.0.1.0/24 --type public
log_success "Public subnet created"
echo ""

# Step 3: Add private subnet to VPC1
log_test "Adding private subnet to VPC1"
sudo ./vpcctl.py add-subnet vpc1 prv 10.0.2.0/24 --type private
log_success "Private subnet created"
echo ""

# Step 4: List VPCs
log_test "Listing all VPCs"
sudo ./vpcctl.py list
echo ""

# Step 5: Test connectivity within VPC1
log_test "Testing connectivity between subnets in VPC1"
if sudo ip netns exec vpc1-prv ping -c 2 10.0.1.1 > /dev/null 2>&1; then
    log_success "VPC1: private → public subnet communication works"
else
    log_error "VPC1: private → public subnet communication failed"
fi
echo ""

# Step 6: Create VPC2
log_test "Creating VPC2 with CIDR 172.16.0.0/16"
sudo ./vpcctl.py create-vpc vpc2 172.16.0.0/16 --interface $IFACE
log_success "VPC2 created"
echo ""

# Step 7: Add subnet to VPC2
log_test "Adding subnet to VPC2"
sudo ./vpcctl.py add-subnet vpc2 web 172.16.1.0/24 --type public
log_success "VPC2 subnet created"
echo ""

# Step 8: Test VPC isolation
log_test "Testing VPC isolation (vpc1 → vpc2 should fail)"
if sudo ip netns exec vpc1-pub ping -c 2 -W 1 172.16.1.1 > /dev/null 2>&1; then
    log_error "VPCs are NOT isolated (unexpected)"
else
    log_success "VPCs are properly isolated"
fi
echo ""

# Step 9: Test NAT from public subnet
log_test "Testing internet access from public subnet"
if sudo ip netns exec vpc1-pub ping -c 2 -W 2 8.8.8.8 > /dev/null 2>&1; then
    log_success "Public subnet has internet access"
else
    log_error "Public subnet cannot reach internet (NAT issue)"
    echo "  Checking NAT rules..."
    sudo iptables -t nat -L POSTROUTING -n | grep 10.0.1
fi
echo ""

# Step 10: Test VPC peering
log_test "Peering VPC1 and VPC2"
sudo ./vpcctl.py peer vpc1 vpc2
log_success "VPCs peered"
echo ""

log_test "Testing cross-VPC communication after peering"
sleep 2
if sudo ip netns exec vpc1-pub ping -c 2 172.16.1.1 > /dev/null 2>&1; then
    log_success "Cross-VPC communication works after peering"
else
    log_error "Cross-VPC communication failed after peering"
fi
echo ""

echo "=== Demo Complete ==="
echo "VPCs will be cleaned up..."
