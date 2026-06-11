# Design Document — Repository Cleanup & Hygiene

This document defines the design and target file list for removing local development noise, legacy agent logs, scratch files, and local databases from Git tracking, turning the repository into a clean, enterprise-grade codebase.

## Selected Approach: Strict Git-Removal (Approach A)
We will untrack files using `git rm --cached` so they are removed from the GitHub repository upon push but preserved in the local development workspace of the user. We will also refine the `.gitignore` rules to keep them permanently untracked.

## Cleanup Target Files

The following categories of files will be removed from Git tracking:

### 1. Root-level Development Text Logs & Scratch Files
- `2026-04-24-210136-claudecode.txt`
- `2026-04-24-233704-claudecode2.txt`
- `CODE_REVIEW_FINDINGS_2026-04-27.txt`
- `FIX_COMPLETION_SUMMARY_2026-04-28.txt`
- `FIX_PLAN_FOR_CLAUDE_CODE.txt`
- `IMPLEMENTATION_PLAN.md`
- `IMPLEMENTATION_SUMMARY_2026-04-27.txt`
- `PHASE_1_COMPLETION.md`
- `TEST_RESULTS_2026-04-28.txt`
- `TESTING_GUIDE.txt`
- `_fix_prompt.py`
- `antigravity_session_v2.1.0_backup.md`
- `claude_code_prompt.md`
- `claude_instructions.md`
- `debug_puller.py`
- `litellm_log.txt`
- `multi-vendor_support_8edae367.plan.md`
- `screenshot.py`
- `test_fixes_comprehensive.py`
- `AI Model`
- `git`

### 2. Databases & Transaction Logs
- `network_manager/network_manager.db` (Database file itself — app initializes database automatically)
- `network_manager.db-shm`
- `network_manager.db-wal`

### 3. Figma JSON & Previews
- `figma_data.json`
- `figma_groups.json`
- `figma_preview.png`
- `figma_preview_2x.png`

### 4. Local Scratch Directory Files
- `scratch/spawn_and_leave.py`
- `scratch/test_agent_tools.py`
- `scratch/test_annotations.py`
- `scratch/test_copilot_signals.py`
- `scratch/test_dialog_signals.py`
- `scratch/test_gns3.py`
- `scratch/test_live_annotations.py`
- `scratch/test_live_gns3.py`
- `scratch/test_live_move.py`

### 5. Old Backups & Legacy UI Code
- `network_manager/gui/agent_dialog_old_backup.py`
- `network_manager/gui/agent_dialog_qt_backup.py`

### 6. Temporary Screenshots & Mockups
- `test_out.png`
- `ui_selfcheck_after_polish.png`
- `ui_selfcheck_after_polish_v2.png`
- `chat_history_mockup.html`

### 7. Obsolete Root Markdown Docs
- `ROUTER_FEATURES.md`
- `future_ideas.md`

### 8. Legacy Scripts inside Codebase
- `network_manager/test_full_audit.py`
- `network_manager/test_routing_protocols.py`
- `network_manager/COPILOT_EVAL_SCENARIOS.txt`
