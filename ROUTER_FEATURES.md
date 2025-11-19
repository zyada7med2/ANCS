# Router Configuration Features Added to ANCS

## Overview
Added comprehensive Router-on-a-Stick and static routing configuration to the Guided Setup Wizard for routers.

## New Features for Routers

### 1. **VLAN Definition Step**
- Define VLANs that the router will route between
- Simple VLAN ID and Name entry
- No port assignment needed (router doesn't have switch ports)

### 2. **Router-on-a-Stick Configuration**
**Physical Interface Selection:**
- FastEthernet0/0
- GigabitEthernet1/0
- GigabitEthernet2/0
- GigabitEthernet3/0
- GigabitEthernet4/0
- GigabitEthernet5/0

**Generated Configuration:**
```cisco
interface FastEthernet0/0
 no shutdown
 exit
interface FastEthernet0/0.10
 encapsulation dot1Q 10
 ip address 192.168.10.1 255.255.255.0
 exit
interface FastEthernet0/0.20
 encapsulation dot1Q 20
 ip address 192.168.20.1 255.255.255.0
 exit
```

### 3. **Static Routing (Optional)**
- Add static routes to external networks
- Common use: Default route to ISP
- Supports network, mask, next-hop, and description

**Example Configuration:**
```cisco
! Default route to ISP
ip route 0.0.0.0 0.0.0.0 203.0.113.1
! Route to branch office
ip route 10.0.0.0 255.0.0.0 192.168.100.1
```

### 4. **DHCP Pools** (existing, now works with router-on-a-stick)
- Automatically assign IPs to end devices
- Configured per VLAN/network

### 5. **Access Control Lists** (existing)
- Security filtering between networks

## Router Wizard Flow

1. **Welcome** - Introduction
2. **Name & Lock** - Device identity and passwords
3. **VLANs (Router-on-a-Stick)** - Define VLANs (NEW)
4. **Router Subinterfaces** - Configure inter-VLAN routing (NEW)
5. **Static Routes** - Add static routes (NEW, optional)
6. **DHCP Pools** - IP address distribution
7. **Access Rules** - Security ACLs
8. **Summary & Save** - Review and apply

## Usage

1. Add a router device in ANCS
2. Click "guided setup (beginner)"
3. Select the router from the device list
4. Follow the wizard steps
5. Review generated configuration
6. Send to router via Serial/Telnet/SSH

## Technical Details

- Router interfaces start at Gi**1**/0, not Gi0/0
- Only FastEthernet0/0 is available (single FE interface)
- Serial interfaces (Serial6/0-3) not yet integrated in wizard (can be added manually)
- Subinterfaces use dot1Q encapsulation for VLAN tagging
- Physical interface must be "no shutdown" for subinterfaces to work

## Benefits

✅ Proper inter-VLAN routing configuration
✅ Industry-standard router-on-a-stick implementation
✅ Static routing support for WAN connections
✅ Beginner-friendly step-by-step wizard
✅ Automatic configuration generation
✅ Separate templates for each config block

