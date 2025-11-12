#!/usr/bin/env python3
"""
vpcctl - Linux VPC Management Tool
Creates and manages virtual VPCs using Linux network namespaces, bridges, and routing
"""

import argparse
import json
import subprocess
import sys
import os
from pathlib import Path
import ipaddress
import hashlib

# Configuration directory
CONFIG_DIR = Path.home() / ".vpcctl"
VPC_STATE_FILE = CONFIG_DIR / "vpcs.json"

class VPCManager:
    def __init__(self):
        CONFIG_DIR.mkdir(exist_ok=True)
        self.state = self._load_state()
    
    def _load_state(self):
        """Load VPC state from disk"""
        if VPC_STATE_FILE.exists():
            with open(VPC_STATE_FILE) as f:
                return json.load(f)
        return {"vpcs": {}}
    
    def _save_state(self):
        """Save VPC state to disk"""
        with open(VPC_STATE_FILE, 'w') as f:
            json.dump(self.state, f, indent=2)
    
    def _run_cmd(self, cmd, check=True, capture=True):
        """Execute shell command and log it"""
        print(f"[CMD] {cmd}")
        if capture:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if check and result.returncode != 0:
                print(f"[ERROR] {result.stderr}")
                raise Exception(f"Command failed: {cmd}")
            return result.stdout.strip()
        else:
            result = subprocess.run(cmd, shell=True)
            if check and result.returncode != 0:
                raise Exception(f"Command failed: {cmd}")
    
    def create_vpc(self, vpc_name, cidr_block, internet_interface="eth0"):
        """Create a new VPC with bridge"""
        if vpc_name in self.state["vpcs"]:
            print(f"[ERROR] VPC {vpc_name} already exists")
            return
        
        bridge_name = f"br-{vpc_name}"
        
        print(f"[INFO] Creating VPC: {vpc_name} with CIDR: {cidr_block}")
        
        # Create bridge
        self._run_cmd(f"ip link add {bridge_name} type bridge")
        self._run_cmd(f"ip link set {bridge_name} up")
        
        # Enable bridge filtering for isolation
        self._run_cmd(f"echo 1 > /proc/sys/net/bridge/bridge-nf-call-iptables", check=False)
        
        # Add iptables rule to block cross-VPC traffic by default
        # Traffic within same bridge is allowed, but different bridges are blocked
        self._run_cmd(f"iptables -A FORWARD -i {bridge_name} -o {bridge_name} -j ACCEPT", check=False)
        self._run_cmd(f"iptables -A FORWARD -i {bridge_name} ! -o {bridge_name} -j DROP", check=False)
        
        # Assign bridge IP (first IP in CIDR)
        network = ipaddress.ip_network(cidr_block)
        bridge_ip = str(list(network.hosts())[0])
        self._run_cmd(f"ip addr add {bridge_ip}/{network.prefixlen} dev {bridge_name}")
        
        # Enable IP forwarding
        self._run_cmd("sysctl -w net.ipv4.ip_forward=1", capture=False)
        
        # Store VPC state
        self.state["vpcs"][vpc_name] = {
            "cidr": cidr_block,
            "bridge": bridge_name,
            "bridge_ip": bridge_ip,
            "internet_interface": internet_interface,
            "subnets": {}
        }
        self._save_state()
        
        print(f"[SUCCESS] VPC {vpc_name} created with bridge {bridge_name}")
    
    def add_subnet(self, vpc_name, subnet_name, subnet_cidr, subnet_type="private"):
        """Add a subnet (namespace) to VPC"""
        if vpc_name not in self.state["vpcs"]:
            print(f"[ERROR] VPC {vpc_name} not found")
            return
        
        vpc = self.state["vpcs"][vpc_name]
        ns_name = f"{vpc_name}-{subnet_name}"
        
        # Shorten interface names to stay under 15 char limit
        name_hash = hashlib.md5(f"{vpc_name}{subnet_name}".encode()).hexdigest()[:6]
        veth_host = f"vh{name_hash}"
        veth_ns = f"vn{name_hash}"
        
        print(f"[INFO] Creating {subnet_type} subnet: {subnet_name} in VPC {vpc_name}")
        
        # Create namespace
        self._run_cmd(f"ip netns add {ns_name}")
        
        # Create veth pair
        self._run_cmd(f"ip link add {veth_host} type veth peer name {veth_ns}")
        
        # Move one end to namespace
        self._run_cmd(f"ip link set {veth_ns} netns {ns_name}")
        
        # Attach host end to bridge
        self._run_cmd(f"ip link set {veth_host} master {vpc['bridge']}")
        self._run_cmd(f"ip link set {veth_host} up")
        
        # Configure namespace interface
        subnet_net = ipaddress.ip_network(subnet_cidr)
        subnet_ip = str(list(subnet_net.hosts())[0])
        subnet_gateway = str(list(subnet_net.hosts())[1])  # Use second IP as gateway
        
        self._run_cmd(f"ip netns exec {ns_name} ip link set lo up")
        self._run_cmd(f"ip netns exec {ns_name} ip addr add {subnet_ip}/{subnet_net.prefixlen} dev {veth_ns}")
        self._run_cmd(f"ip netns exec {ns_name} ip link set {veth_ns} up")
        
        # Add IP to bridge for this subnet's gateway
        self._run_cmd(f"ip addr add {subnet_gateway}/{subnet_net.prefixlen} dev {vpc['bridge']}")
        
        # Add default route through subnet gateway
        self._run_cmd(f"ip netns exec {ns_name} ip route add default via {subnet_gateway}")
        
        # Configure NAT for public subnets
        if subnet_type == "public":
            self._setup_nat(vpc_name, subnet_cidr)
        
        # Store subnet state
        vpc["subnets"][subnet_name] = {
            "cidr": subnet_cidr,
            "type": subnet_type,
            "namespace": ns_name,
            "ip": subnet_ip,
            "gateway": subnet_gateway,
            "veth_host": veth_host,
            "veth_ns": veth_ns
        }
        self._save_state()
        
        print(f"[SUCCESS] Subnet {subnet_name} created in namespace {ns_name}")
    
    def _setup_nat(self, vpc_name, subnet_cidr):
        """Setup NAT for public subnet"""
        vpc = self.state["vpcs"][vpc_name]
        iface = vpc["internet_interface"]
        
        print(f"[INFO] Setting up NAT for subnet {subnet_cidr}")
        
        # Add MASQUERADE rule
        self._run_cmd(
            f"iptables -t nat -A POSTROUTING -s {subnet_cidr} -o {iface} -j MASQUERADE"
        )
        
        # Allow forwarding
        self._run_cmd(f"iptables -A FORWARD -i {vpc['bridge']} -o {iface} -j ACCEPT")
        self._run_cmd(f"iptables -A FORWARD -o {vpc['bridge']} -i {iface} -j ACCEPT")
    
    def peer_vpcs(self, vpc1_name, vpc2_name):
        """Peer two VPCs together"""
        if vpc1_name not in self.state["vpcs"] or vpc2_name not in self.state["vpcs"]:
            print("[ERROR] One or both VPCs not found")
            return
        
        vpc1 = self.state["vpcs"][vpc1_name]
        vpc2 = self.state["vpcs"][vpc2_name]
        
        # Use shorter names to avoid 15 char limit
        peer_hash = hashlib.md5(f"{vpc1_name}{vpc2_name}".encode()).hexdigest()[:6]
        peer_veth1 = f"pr1{peer_hash}"
        peer_veth2 = f"pr2{peer_hash}"
        
        print(f"[INFO] Peering VPC {vpc1_name} with {vpc2_name}")
        
        # Clean up any existing peer interfaces first
        self._run_cmd(f"ip link del {peer_veth1}", check=False)
        self._run_cmd(f"ip link del {peer_veth2}", check=False)
        
        # Create veth pair between bridges
        self._run_cmd(f"ip link add {peer_veth1} type veth peer name {peer_veth2}")
        
        # Attach to respective bridges (NO IP assignment - this prevents auto routes)
        self._run_cmd(f"ip link set {peer_veth1} master {vpc1['bridge']}")
        self._run_cmd(f"ip link set {peer_veth1} up")
        
        self._run_cmd(f"ip link set {peer_veth2} master {vpc2['bridge']}")
        self._run_cmd(f"ip link set {peer_veth2} up")
        
        # Routes will use the bridges themselves as the gateway
        # Since the veth pairs connect the bridges, traffic flows through them
        self._run_cmd(f"ip route replace {vpc2['cidr']} dev {vpc1['bridge']}")
        self._run_cmd(f"ip route replace {vpc1['cidr']} dev {vpc2['bridge']}")
        
        # Remove isolation rules between these two VPCs
        self._run_cmd(f"iptables -I FORWARD -i {vpc1['bridge']} -o {vpc2['bridge']} -j ACCEPT", check=False)
        self._run_cmd(f"iptables -I FORWARD -i {vpc2['bridge']} -o {vpc1['bridge']} -j ACCEPT", check=False)
        
        print(f"[SUCCESS] VPCs {vpc1_name} and {vpc2_name} peered")
    
    def apply_firewall(self, vpc_name, subnet_name, policy_file):
        """Apply firewall rules from JSON policy"""
        if vpc_name not in self.state["vpcs"]:
            print(f"[ERROR] VPC {vpc_name} not found")
            return
        
        vpc = self.state["vpcs"][vpc_name]
        if subnet_name not in vpc["subnets"]:
            print(f"[ERROR] Subnet {subnet_name} not found")
            return
        
        subnet = vpc["subnets"][subnet_name]
        ns_name = subnet["namespace"]
        
        with open(policy_file) as f:
            policy = json.load(f)
        
        print(f"[INFO] Applying firewall rules to {subnet_name}")
        
        # Apply ingress rules
        for rule in policy.get("ingress", []):
            port = rule["port"]
            proto = rule["protocol"]
            action = rule["action"].upper()
            
            if action == "ALLOW":
                cmd = f"ip netns exec {ns_name} iptables -A INPUT -p {proto} --dport {port} -j ACCEPT"
            else:
                cmd = f"ip netns exec {ns_name} iptables -A INPUT -p {proto} --dport {port} -j DROP"
            
            self._run_cmd(cmd)
            print(f"  - {action} {proto}/{port}")
        
        print(f"[SUCCESS] Firewall rules applied")
    
    def list_vpcs(self):
        """List all VPCs"""
        if not self.state["vpcs"]:
            print("No VPCs found")
            return
        
        for vpc_name, vpc_data in self.state["vpcs"].items():
            print(f"\nVPC: {vpc_name}")
            print(f"  CIDR: {vpc_data['cidr']}")
            print(f"  Bridge: {vpc_data['bridge']} ({vpc_data['bridge_ip']})")
            print(f"  Subnets:")
            for subnet_name, subnet_data in vpc_data["subnets"].items():
                print(f"    - {subnet_name} ({subnet_data['type']}): {subnet_data['cidr']}")
    
    def delete_vpc(self, vpc_name):
        """Delete VPC and all subnets"""
        if vpc_name not in self.state["vpcs"]:
            print(f"[ERROR] VPC {vpc_name} not found")
            return
        
        vpc = self.state["vpcs"][vpc_name]
        
        print(f"[INFO] Deleting VPC: {vpc_name}")
        
        # Delete subnets
        for subnet_name, subnet in vpc["subnets"].items():
            ns_name = subnet["namespace"]
            print(f"  - Deleting subnet {subnet_name}")
            
            # Delete namespace (automatically removes interfaces)
            self._run_cmd(f"ip netns del {ns_name}", check=False)
            
            # Clean up host veth
            self._run_cmd(f"ip link del {subnet['veth_host']}", check=False)
        
        # Clean up NAT rules
        for subnet_name, subnet in vpc["subnets"].items():
            if subnet["type"] == "public":
                self._run_cmd(
                    f"iptables -t nat -D POSTROUTING -s {subnet['cidr']} -o {vpc['internet_interface']} -j MASQUERADE",
                    check=False
                )
        
        # Clean up isolation rules
        self._run_cmd(f"iptables -D FORWARD -i {vpc['bridge']} -o {vpc['bridge']} -j ACCEPT", check=False)
        self._run_cmd(f"iptables -D FORWARD -i {vpc['bridge']} ! -o {vpc['bridge']} -j DROP", check=False)
        
        # Delete bridge
        self._run_cmd(f"ip link del {vpc['bridge']}", check=False)
        
        # Remove from state
        del self.state["vpcs"][vpc_name]
        self._save_state()
        
        print(f"[SUCCESS] VPC {vpc_name} deleted")

def main():
    parser = argparse.ArgumentParser(description="VPC Management CLI")
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # Create VPC
    create = subparsers.add_parser("create-vpc", help="Create a new VPC")
    create.add_argument("name", help="VPC name")
    create.add_argument("cidr", help="CIDR block (e.g., 10.0.0.0/16)")
    create.add_argument("--interface", default="eth0", help="Internet interface")
    
    # Add subnet
    subnet = subparsers.add_parser("add-subnet", help="Add subnet to VPC")
    subnet.add_argument("vpc", help="VPC name")
    subnet.add_argument("name", help="Subnet name")
    subnet.add_argument("cidr", help="Subnet CIDR")
    subnet.add_argument("--type", choices=["public", "private"], default="private")
    
    # Peer VPCs
    peer = subparsers.add_parser("peer", help="Peer two VPCs")
    peer.add_argument("vpc1", help="First VPC")
    peer.add_argument("vpc2", help="Second VPC")
    
    # Apply firewall
    firewall = subparsers.add_parser("apply-firewall", help="Apply firewall rules")
    firewall.add_argument("vpc", help="VPC name")
    firewall.add_argument("subnet", help="Subnet name")
    firewall.add_argument("policy", help="Policy JSON file")
    
    # List VPCs
    subparsers.add_parser("list", help="List all VPCs")
    
    # Delete VPC
    delete = subparsers.add_parser("delete-vpc", help="Delete VPC")
    delete.add_argument("name", help="VPC name")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    # Check root privileges
    if os.geteuid() != 0:
        print("[ERROR] This tool requires root privileges. Run with sudo.")
        sys.exit(1)
    
    manager = VPCManager()
    
    if args.command == "create-vpc":
        manager.create_vpc(args.name, args.cidr, args.interface)
    elif args.command == "add-subnet":
        manager.add_subnet(args.vpc, args.name, args.cidr, args.type)
    elif args.command == "peer":
        manager.peer_vpcs(args.vpc1, args.vpc2)
    elif args.command == "apply-firewall":
        manager.apply_firewall(args.vpc, args.subnet, args.policy)
    elif args.command == "list":
        manager.list_vpcs()
    elif args.command == "delete-vpc":
        manager.delete_vpc(args.name)

if __name__ == "__main__":
    main()
