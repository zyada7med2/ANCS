# Design Document: Graduation Presentation for ANCS Agent Architecture

## Overview
This document outlines the detailed structure and technical design of the 15-slide PowerPoint presentation created for the ANCS graduation project defense. The target audience is academic professors in network and computer engineering, requiring a professional, technically rigorous, yet clean presentation.

## Presentation Theme and Styling
*   **Color Palette**: Dark, professional layout (deep dark blue backgrounds `#0B0F19`, high-contrast text, glowing cyan `#00F0FF` and purple accents).
*   **Typography**: Clean, premium modern sans-serif fonts (e.g., Arial or Calibri for standard compatibility, structured into strict headings and bullet points).
*   **Layouts**: Standard 16:9 widescreen format, with distinct layouts for:
    *   Title slides
    *   System block diagrams (represented as structured text hierarchies or bullet columns)
    *   Core AI troubleshooting loops
    *   Code/algorithm snippets (formatted clearly for readability)
    *   Telemetry and evaluation case studies

## Slide-by-Slide Content Mapping

### Part 1: Project Scope & System Core (Slides 1–5)
1.  **Slide 1: Title Slide (Academic Branding)**
    *   *Title*: ANCS: Autonomous Network Configuration & Orchestration System
    *   *Subtitle*: An Agentic AI Copilot for Automated Cisco IOS Provisioning, Auditing, and Diagnostics in GNS3 Environments
    *   *Meta*: Presentation for Graduation Project Defense.
2.  **Slide 2: Introduction & Motivation (Why ANCS?)**
    *   *Concept*: Outline traditional network management pain points (prone to human configuration errors, 80% of outages) and Netmiko/Ansible programming requirements.
    *   *Solution*: An intelligent desktop orchestration platform equipped with an autonomous virtual assistant that thinks and acts like a network engineer.
3.  **Slide 3: Overall System Architecture (High-Level MVC)**
    *   *Concept*: Breakdown of decoupled MVVM/MVC:
        *   **Frontend**: Modern HTML/CSS HUD.
        *   **Bridge**: `QWebEngineView` and `QWebChannel` async JSON messaging.
        *   **Backend Core**: Python/SQLite DB (`PRAGMA WAL` locks + thread-safe global `db_lock`).
4.  **Slide 4: GNS3 Live API & Staggered Session Pooling**
    *   *Concept*: Explains communication with GNS3 REST API, Telnet IAC cleanser, and staggered pooling (staggering connections by 1.5 seconds) to prevent console socket collisions.
5.  **Slide 5: The ConfigEngine & Syntax Generator**
    *   *Concept*: Breakdown of local programmatic config generation: Layer 2 access switches, Layer 3 core switches (SVIs, STP roots), and routers (RIP/OSPF/EIGRP subinterfaces). Highlight `! BLOCK X` header formatting for safe chunked deployments.

### Part 2: Dynamic LLM & Cognitive Engineering (Slides 6–10)
6.  **Slide 6: The AI Agent's Cognitive Model (Cisco Troubleshooting Loop)**
    *   *Concept*: The LLM's logical troubleshooting cycle mapping Cisco engineering workflows: **Thought** (Hypothesis) → **Action** (Command/Tool) → **Observation** (Outcome Analysis) → **Next Thought**.
7.  **Slide 7: Reflection-Based Tool Calling (`_build_openai_tools`)**
    *   *Concept*: Dynamic python-to-JSON-schema translation. Programmatic inspection of parameters and docstrings (`inspect.signature`) to generate OpenAI/Gemini schemas on-the-fly.
8.  **Slide 8: Context Optimization: Compression & Sliding Window**
    *   *Concept*: Token optimization techniques:
        *   *Context Compression (`_compress_context`)*: Truncating old logs/configs (>6 turns) to 200 characters.
        *   *Sliding Window Trimming (`_truncate_history`)*: Safe 20-message window that preserves system prompts and tool call boundaries.
9.  **Slide 9: Safety Guardrails: Hostname & Providence Checks**
    *   *Concept*:
        *   *Hostname Guardrail*: Regex checker blocking cross-device mismatches (e.g. R1's config to SW1).
        *   *Providence Check*: Deploy blocker for unverified configurations.
10. **Slide 10: Human-in-the-Loop (HITL) Interception**
    *   *Concept*: Interactive interception of `generate_and_deploy_device_config`. Pushes visual diff comparison to GUI. Explains Rejection Respect Rules.

### Part 3: Low-Level Engineering & UI Telemetry (Slides 11–15)
11. **Slide 11: Staggered Parallel Execution & Jitter Scheduling**
    *   *Concept*: Multi-device concurrent deployment via `ThreadPoolExecutor` and a staggered jitter scheduling algorithm (0.5s intervals) to prevent GNS3 Telnet port collisions.
12. **Slide 12: Interactive Prompt Handling & Cisco Error Parsing**
    *   *Concept*:
        *   *Prompt Bypass*: Regex-based scanner for interactive prompts (like `[confirm]`) automatically feeding `yes\r\n`.
        *   *Live CLI Error Scan*: Intercepting `% Invalid input` and flagging error badges to the agent thread.
13. **Slide 13: Bidirectional Web Bridge & Topology Coordinate Scaler**
    *   *Concept*:
        *   *Bridge*: Bidirectional `QWebChannel` bridge serialization.
        *   *Scaler*: GNS3 pixel-to-percentage canvas scaler (15%-85% margins).
        *   *Wire Offsets*: Perpendicular wire offsets for port labels.
14. **Slide 14: System Evaluation: Network Audits & Diagnostics**
    *   *Concept*: Core diagnostic tool suite:
        *   *Golden Trio Snapshot*: Capture interfaces, ARP, and routing in ~6s.
        *   *Network Audits*: Detecting missing enable secrets, open VTY lines, mismatched protocols.
        *   *Path-Tracing*: Hop-by-hop tracking using routing table entry lookups.
15. **Slide 15: Conclusion & Future Work**
    *   *Contributions*: A robust, safe, agentic Cisco IOS orchestrator bridging dynamic LLM reasoning with strict, deterministic network guardrails.
    *   *Future Work*: Adding BGP troubleshooting, traffic analysis, and physical DevNet lab integrations.

## Implementation Details
The presentation is compiled programmatically into a professional PowerPoint deck (`ancs_graduation_presentation.pptx`) in the root workspace folder, utilizing a Python automation script that handles slide layout, typography styles, and slide contents.
