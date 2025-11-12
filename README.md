# vpcctl - Linux VPC Management Tool

A command-line tool to create and manage Virtual Private Clouds (VPCs) on Linux using native networking primitives.

## Features

- ✅ Create isolated VPCs with custom CIDR blocks
- ✅ Add public and private subnets
- ✅ Automatic NAT gateway configuration
- ✅ VPC peering for cross-VPC communication
- ✅ JSON-based firewall policies
- ✅ Complete lifecycle management (create, list, delete)
- ✅ Clean teardown with no orphaned resources

## Prerequisites

- Linux OS (Ubuntu 20.04+, Debian, CentOS, etc.)
- Python 3.6 or higher
- Root privileges (sudo)
- `iproute2` package installed
- `iptables` installed

```bash
# Install dependencies (Ubuntu/Debian)
sudo apt-get update
sudo apt-get install -y python3 iproute2 iptables bridge-utils

# Install dependencies (CentOS/RHEL)
sudo yum install -y python3 iproute iptables bridge-utils
```

## Installation

1. Clone the repository:

```bash
git clone https://github.com/yourusername/vpcctl.git
cd vpcctl
```

2. Make the script executable:

```bash
chmod +x vpcctl.py
```

3. Optionally, create a symlink for system-wide access:

```bash
sudo ln -s $(pwd)/vpcctl.py /usr/local/bin/vpcctl
```

## Quick Start

### Create a VPC

```bash
sudo ./vpcctl.py create-vpc myvpc 10.0.0.0/16 --interface eth0
```

### Add Subnets

```bash
# Add public subnet (with internet access)
sudo ./vpcctl.py add-subnet myvpc public 10.0.1.0/24 --type public

# Add private subnet (isolated)
sudo ./vpcctl.py add-subnet myvpc private 10.0.2.0/24 --type private
```

### List VPCs

```bash
sudo ./vpcctl.py list
```

### Deploy Test Server

```bash
# Start HTTP server in public subnet
sudo ip netns exec myvpc-public python3 -m http.server 8080 &

# Test connectivity from private subnet
sudo ip netns exec myvpc-private curl http://10.0.1.1:8080
```

### Delete VPC

```bash
sudo ./vpcctl.py delete-vpc myvpc
```

## Usage Examples

### Example 1: Basic VPC with Public and Private Subnets

```bash
# Create VPC
sudo ./vpcctl.py create-vpc prod 10.0.0.0/16

# Add subnets
sudo ./vpcctl.py add-subnet prod web 10.0.1.0/24 --type public
sudo ./vpcctl.py add-subnet prod db 10.0.2.0/24 --type private

# Test connectivity
sudo ip netns exec prod-web ping 10.0.2.1  # Should work
sudo ip netns exec prod-web ping 8.8.8.8   # Should work (NAT)
sudo ip netns exec prod-db ping 8.8.8.8    # Should fail (no internet)
```

### Example 2: Multi-VPC Setup with Peering

```bash
# Create first VPC
sudo ./vpcctl.py create-vpc vpc1 10.0.0.0/16
sudo ./vpcctl.py add-subnet vpc1 app 10.0.1.0/24 --type public

# Create second VPC
sudo ./vpcctl.py create-vpc vpc2 172.16.0.0/16
sudo ./vpcctl.py add-subnet vpc2 service 172.16.1.0/24 --type public

# Test isolation (should fail)
sudo ip netns exec vpc1-app ping 172.16.1.1

# Enable peering
sudo ./vpcctl.py peer vpc1 vpc2

# Test connectivity (should now work)
sudo ip netns exec vpc1-app ping 172.16.1.1
```

### Example 3: Firewall Rules

Create `firewall.json`:

```json
{
  "subnet": "10.0.1.0/24",
  "ingress": [
    {"port": 80, "protocol": "tcp", "action": "allow"},
    {"port": 443, "protocol": "tcp", "action": "allow"},
    {"port": 22, "protocol": "tcp", "action": "deny"}
  ]
}
```

Apply rules:

```bash
sudo ./vpcctl.py apply-firewall myvpc public firewall.json
```

## Command Reference

### create-vpc

Create a new VPC with specified CIDR block.

```bash
sudo ./vpcctl.py create-vpc <name> <cidr> [--interface <interface>]
```

**Arguments:**
- `name`: Unique VPC name
- `cidr`: IP address range (e.g., 10.0.0.0/16)
- `--interface`: Internet-facing network interface (default: eth0)

**Example:**
```bash
sudo ./vpcctl.py create-vpc production 192.168.0.0/16 --interface ens33
```

### add-subnet

Add a subnet to an existing VPC.

```bash
sudo ./vpcctl.py add-subnet <vpc> <name> <cidr> [--type <public|private>]
```

**Arguments:**
- `vpc`: VPC name
- `name`: Subnet name
- `cidr`: Subnet IP range
- `--type`: `public` (with NAT) or `private` (default: private)

**Example:**
```bash
sudo ./vpcctl.py add-subnet production frontend 192.168.1.0/24 --type public
```

### peer

Establish peering connection between two VPCs.

```bash
sudo ./vpcctl.py peer <vpc1> <vpc2>
```

**Example:**
```bash
sudo ./vpcctl.py peer vpc-east vpc-west
```

### apply-firewall

Apply firewall rules from JSON policy file.

```bash
sudo ./vpcctl.py apply-firewall <vpc> <subnet> <policy_file>
```

**Example:**
```bash
sudo ./vpcctl.py apply-firewall prod web firewall-rules.json
```

### list

Display all VPCs and their subnets.

```bash
sudo ./vpcctl.py list
```

### delete-vpc

Remove VPC and all associated resources.

```bash
sudo ./vpcctl.py delete-vpc <name>
```

**Example:**
```bash
sudo ./vpcctl.py delete-vpc production
```

## Architecture

```
Host System
├── VPC 1 (10.0.0.0/16)
│   ├── Bridge: br-vpc1
│   ├── Public Subnet (10.0.1.0/24)
│   │   └── Namespace: vpc1-public
│   └── Private Subnet (10.0.2.0/24)
│       └── Namespace: vpc1-private
│
└── VPC 2 (172.16.0.0/16)
    ├── Bridge: br-vpc2
    └── Subnet (172.16.1.0/24)
        └── Namespace: vpc2-subnet
```

## Testing

Run the test suite:

```bash
sudo bash test_demo.sh
```

## Troubleshooting

### Problem: Cannot reach internet from public subnet

**Solution:** Check your interface name:

```bash
ip link show
# Update --interface parameter with correct interface name
```

### Problem: "Operation not permitted"

**Solution:** Run with sudo:

```bash
sudo ./vpcctl.py <command>
```

### Problem: Namespace already exists

**Solution:** Delete existing VPC first:

```bash
sudo ./vpcctl.py delete-vpc <vpc-name>
```

### Problem: Routing not working

**Solution:** Verify IP forwarding is enabled:

```bash
sudo sysctl -w net.ipv4.ip_forward=1
```

## Logging

All operations are logged with descriptive output:
- `[CMD]` - Command being executed
- `[INFO]` - Information messages
- `[SUCCESS]` - Operation completed successfully
- `[ERROR]` - Error messages

VPC state is stored in `~/.vpcctl/vpcs.json`

## Cleanup

To remove all VPCs and clean up:

```bash
# List all VPCs
sudo ./vpcctl.py list

# Delete each VPC
sudo ./vpcctl.py delete-vpc vpc1
sudo ./vpcctl.py delete-vpc vpc2
```

## Known Limitations

- Requires root privileges for all operations
- IPv4 only (IPv6 not currently supported)
- No DHCP server (static IP assignment)
- No built-in DNS resolution
- Maximum of ~250 namespaces per system (kernel limit)

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

MIT License - See LICENSE file for details

## Acknowledgments

Built using Linux kernel networking features:
- Network namespaces
- veth pairs
- Linux bridges
- iptables/netfilter
- iproute2 tools

## Further Reading

- [Linux Network Namespaces](https://man7.org/linux/man-pages/man7/network_namespaces.7.html)
- [Linux Bridge](https://wiki.linuxfoundation.org/networking/bridge)
- [iptables Documentation](https://www.netfilter.org/documentation/)
- [AWS VPC Concepts](https://docs.aws.amazon.com/vpc/)

## Support

For issues, questions, or suggestions:
- Open an issue on GitHub
- Check existing issues for solutions

---

Made with ❤️ for the Linux networking community
