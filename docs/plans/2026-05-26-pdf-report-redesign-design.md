# Design Document: Professional Network Documentation PDF Redesign

This document outlines the layout, styling, and data-mapping architecture to upgrade the ANCS Network Documentation PDF generation. The goal is to provide a highly professional, academic/industry-standard network log that accurately chronicles the deployed network configuration while generating context-aware reference designs for services not currently deployed.

## Visual Design & Styling System

To achieve an industry-standard layout matching professional Cisco design deliverables, we will use a clean HTML + CSS blueprint formatted for A4/Letter size.

### Typography
- **Primary Font Family:** `Arial, Helvetica, sans-serif` for clean cross-platform PDF rendering.
- **Monospace Font Family:** `Consolas, "Courier New", monospace` for configuration syntax and CLI commands.

### Color Palette
- **Primary Heading Color:** Deep corporate blue (`#2F5496`) used for titles, part names, and major headings.
- **Secondary Accent:** Medium steel blue (`#41719C`) for subsections.
- **Body Text:** Slate charcoal (`#2D3748`) for soft, professional readability.
- **Table Headers:** Shaded background (`#F1F5F9`) with dark slate text (`#1E293B`).
- **Table Borders:** Clean, thin, solid light gray grid lines (`1px solid #CBD5E1`).

### Page & Layout Rules
- **Margins:** A standard margin configuration for letter format: `@page { size: letter; margin: 1.0in; }`.
- **Page Break Control:** Avoid half-cut table rows and headers using `tr, pre, .section-card { page-break-inside: avoid; }`.
- **Part Separation:** Start Parts 2 through 5 on new pages using page break classes.

---

## The 13-Section Structured NDD Formula

The report will organize the compiled data into the following Parts and Sections:

### 🟢 Part 1: IP Addressing & Logical Design
*   **1. Executive Summary:** A dynamically generated introductory paragraph summarizing the project, counting the active routers/switches, and stating the active routing protocols detected.
*   **2. Device Inventory & Platform Specifications:** A table showing Name, Platform Type, IP, Console/Management port, and Operational Roles.
*   **3. Logical Subnet Allocation:** A table displaying the global IP subnets and ranges allocated per device.
*   **4. VLAN Subnet Design (Detailed):** A table logging VLAN IDs, Names, IP subnets, Gateway VIPs, and Helper IPs parsed from SVIs.

### 🟡 Part 2: Physical Topology & Redundancy
*   **5. Physical Connection Matrix:** A structured table displaying port-to-port connections between nodes derived from GNS3 link coordinates.
*   **6. Out-of-Band (OOB) Management:** Details the console ports, terminal server connections, and secure SSH configuration parameters.

### 🔵 Part 3: Routing Design & WAN Protocols
*   **7. WAN IP Addressing & Links:** A table dedicated to point-to-point links (detected by `/30` mask interfaces) and WAN edge configurations.
*   **8. Routing Configuration & AS Map:** Records OSPF/BGP/EIGRP configuration blocks, process IDs, and networks.

### 🟠 Part 4: L2 Switching & Redundancy Protocols
*   **9. Link Aggregation & EtherChannels:** Logs LACP channel-groups, bundle interfaces, and physical port assignments.
*   **10. Spanning-Tree & Gateway Redundancy:** Outlines STP modes, root bridge priorities, and HSRP/VRRP gateway configurations.

### 🔴 Part 5: Security, Services & QoS
*   **11. Security Access Control (Firewall & ACLs):** Lists firewall inside/outside interfaces and access list rules.
*   **12. Network Infrastructure Services:** Logs DHCP pools, lease times, DNS settings, and NTP configurations.
*   **13. QoS Strategy & Recommendations:** Classifies voice, signaling, and data traffic with DSCP markings.

---

## Dynamic Data Parsing & Reference Fallbacks

The Python generator in `network_manager/ai_agent.py` will parse raw configurations and SQLite tables:

1.  **Logical & Interface Parsing:** Extracts interface IPs, speeds, and subnets.
2.  **VLAN/SVI Parsing:** Parses `vlan X` and `interface VlanX` structures.
3.  **Active Protocols:** Parses `router ospf`, `router eigrp`, `router bgp`, `ip route` configurations.
4.  **Reference Fallbacks:** If a device configuration does not contain HSRP, EtherChannel, ACLs, Firewall policies, VPN, or QoS settings:
    *   The report will display a clean warning: *"[Service] not configured on this network."*
    *   Below the warning, it will print a **Reference Best-Practice Implementation Template** (e.g., standard Cisco IOS crypto commands or Spanning-Tree priority configurations) customized with the active subnets of the network, serving as an engineering reference.
