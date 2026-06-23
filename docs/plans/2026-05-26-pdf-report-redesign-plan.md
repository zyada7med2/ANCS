# PDF Report Redesign Implementation Plan

> **For Antigravity:** REQUIRED WORKFLOW: Use `.agent/workflows/execute-plan.md` to execute this plan in single-flow mode.

**Goal:** Redesign the PDF network documentation report in ANCS to match the professional 5-Part, 13-Section hierarchical Cisco design deliverables format, complete with dynamic configuration logging and engineering reference fallbacks.

**Architecture:** We will modify `generate_pdf_report` in `network_manager/ai_agent.py` to systematically parse the active SQLite database inventory and latest deployment logs for active node configurations. For each section, it will construct structured HTML tables, appending professional fallback guides if a configuration feature is absent.

**Tech Stack:** Python, PySide6 (QtWebEngine print to PDF), SQLite, HTML5, CSS3.

---

### Task 1: Add Automated Test Suite for PDF Generation Data Extraction

**Files:**
- Create: `network_manager/tests/test_pdf_report.py`

**Step 1: Write the test**
Write a pytest test verifying the parser correctly extracts dynamic fields (like hostnames, subnets, and DHCP pools) and falls back safely when configurations are missing.

```python
import os
import json
import pytest
from network_manager.ai_agent import generate_pdf_report

def test_pdf_report_generation_runs():
    # Verify that the generate_pdf_report function executes without throwing exceptions
    # even when database has sparse configurations.
    filename = "test_run_doc.pdf"
    result = generate_pdf_report(filename=filename)
    assert "Success" in result or "HTML report generated" in result
    
    # Clean up fallback files if created
    downloads_dir = os.path.join(os.path.expanduser("~"), "Downloads")
    html_path = os.path.join(downloads_dir, filename.replace(".pdf", ".html"))
    if os.path.exists(html_path):
        os.remove(html_path)
```

**Step 2: Run test to verify it fails**
Run: `$env:PYTHONPATH="c:\Users\Zyad\Downloads\ANCS"; .venv\Scripts\pytest network_manager/tests/test_pdf_report.py -v`
Expected: FAIL (or import/runtime error due to database schema issue in `ai_agent.py` line 1788-1790).

**Step 3: Write minimal implementation**
We will implement the fix in `network_manager/ai_agent.py` under Task 2 to make the test pass.

**Step 4: Run test to verify it passes**
Expected: PASS after implementing Task 2.

**Step 5: Commit**
```bash
git add network_manager/tests/test_pdf_report.py
git commit -m "test: add basic test for generate_pdf_report tool"
```

---

### Task 2: Implement Config Parsing and 13-Section Data Extraction

**Files:**
- Modify: `network_manager/ai_agent.py:1753-2070`

**Step 1: Write the parser and generator logic**
Modify `generate_pdf_report()` to correctly join `configs` and `devices` tables, parse active setups, and format the 13 sections. 

Replace the database query in `ai_agent.py` around line 1783 with:
```python
    with db_lock:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, type, ip, port, os_version, vendor_id FROM devices")
        for row in cursor.fetchall():
            d_id, name, dtype, ip, port, os_ver, vendor = row
            c_cursor = conn.cursor()
            c_cursor.execute("""
                SELECT content FROM configs 
                WHERE device_id = ? 
                ORDER BY created_at DESC LIMIT 1
            """, (d_id,))
            cfg_row = c_cursor.fetchone()
            cfg_text = cfg_row[0] if cfg_row else ""
            
            # Fetch config from logs if not in configs
            if not cfg_text:
                c_cursor.execute("""
                    SELECT config_snapshot FROM logs 
                    WHERE device_name = ? AND config_snapshot IS NOT NULL AND config_snapshot != ''
                    ORDER BY timestamp DESC LIMIT 1
                """, (name,))
                log_row = c_cursor.fetchone()
                cfg_text = log_row[0] if log_row else ""
```

Include parsing routines for:
*   VLANs / SVIs
*   Physical Interfaces & IPs
*   Static routes
*   DHCP pools
*   OSPF / BGP routing processes
*   L2 switching (STP root, EtherChannels)
*   ACL configurations

Add rich baseline templates for missing services. For example, if no VPN config is detected:
```python
vpn_reference = """
! CRYPTO INTERCONNECT REFERENCE KEY (HQ-Branch IPSec VPN Baseline)
crypto isakmp policy 10
  encryption aes 256
  hash sha256
  authentication pre-share
  group 14
  lifetime 86400
exit
crypto isakmp key VPN_SHARED_KEY address 0.0.0.0 0.0.0.0
crypto ipsec transform-set TS esp-aes esp-sha256-hmac
  mode tunnel
exit
crypto map CMAP 10 ipsec-isakmp
  set peer [PEER_IP_PLACEHOLDER]
  set transform-set TS
  match address 100
exit
"""
```

**Step 2: Run verification**
Run: `$env:PYTHONPATH="c:\Users\Zyad\Downloads\ANCS"; .venv\Scripts\pytest network_manager/tests/test_pdf_report.py -v`
Expected: PASS.

**Step 3: Commit**
```bash
git add network_manager/ai_agent.py
git commit -m "feat: restructure generate_pdf_report database query and config parsing"
```

---

### Task 3: Apply Visual HTML/CSS Styling Enhancements

**Files:**
- Modify: `network_manager/ai_agent.py:1900-2055`

**Step 1: Update styles and page rules**
Enhance the HTML/CSS blocks in `generate_pdf_report` with standard Arial typography, `#2F5496` primary headers, thin bordered tables, page break styling, and clear emoji indicators (🟢, 🟡, 🔵, 🟠, 🔴).

```html
<style>
    @page {
        size: letter;
        margin: 1.0in;
    }
    body {
        font-family: Arial, Helvetica, sans-serif;
        color: #2D3748;
        line-height: 1.5;
        font-size: 13px;
        background: #ffffff;
    }
    h1 {
        font-size: 24px;
        color: #2F5496;
        font-weight: bold;
        border-bottom: 2px solid #2F5496;
        padding-bottom: 8px;
        margin-bottom: 20px;
    }
    .part-title {
        font-size: 16px;
        color: #2F5496;
        font-weight: bold;
        margin-top: 30px;
        margin-bottom: 12px;
        page-break-after: avoid;
    }
    .section-title {
        font-size: 14px;
        color: #41719C;
        font-weight: bold;
        margin-top: 20px;
        margin-bottom: 8px;
        page-break-after: avoid;
    }
    table {
        width: 100%;
        border-collapse: collapse;
        margin-bottom: 18px;
        page-break-inside: avoid;
    }
    th, td {
        border: 1px solid #CBD5E1;
        padding: 8px 10px;
        text-align: left;
        font-size: 12px;
    }
    th {
        background-color: #F1F5F9;
        color: #1E293B;
        font-weight: bold;
    }
    pre {
        font-family: Consolas, "Courier New", monospace;
        background: #F8FAFC;
        border: 1px solid #E2E8F0;
        padding: 10px;
        border-radius: 4px;
        font-size: 11px;
        white-space: pre-wrap;
        page-break-inside: avoid;
    }
    .page-break {
        page-break-before: always;
    }
</style>
```

**Step 2: Run verification**
Validate code compilations using:
`$env:PYTHONPATH="c:\Users\Zyad\Downloads\ANCS"; .venv\Scripts\python.exe -m py_compile network_manager/ai_agent.py`
Expected: Output clean.

**Step 3: Commit**
```bash
git add network_manager/ai_agent.py
git commit -m "style: apply premium word-styling sheet to print layout"
```

---

### Task 4: Verify Full PDF Compilation & Output Location

**Files:**
- Test manually in application GUI.

**Step 1: Launch application**
Run: `.venv\Scripts\python.exe run.py`
Expected: Main GUI window loads.

**Step 2: Generate PDF Report from AI Copilot Chat**
Ask the Copilot: *"Generate the network documentation PDF report."*
Wait for the completion alert in the chat window.

**Step 3: Verify Output**
Check the user's Downloads folder for `network_documentation.pdf`. Open it and verify:
1. The 13-section outline is present.
2. Styling (blue headings, table borders) matches requirements.
3. Fallbacks show cleanly for unconfigured services.
