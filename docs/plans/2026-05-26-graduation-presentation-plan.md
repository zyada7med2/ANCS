# ANCS Graduation Presentation Generation Plan

> **For Antigravity:** REQUIRED WORKFLOW: Use `.agent/workflows/execute-plan.md` to execute this plan in single-flow mode.

**Goal:** Programmatically generate a beautiful, academic-grade, highly-detailed 15-slide PowerPoint presentation (`ANCS_Agent_Graduation_Presentation.pptx`) in the workspace, highlighting the ANCS Agent's custom cognitive engineering and PySide6 integration.

**Architecture:** We will create a Python script using the PEP 723 inline dependency specification so `uv run` can automatically manage and run it with `python-pptx` without polluting the workspace's main virtual environment. The script will apply professional academic styling (dark navy backgrounds, high-contrast text, cyan and purple accents) and generate all 15 detailed slides.

**Tech Stack:** Python 3, `python-pptx` (installed automatically via `uv run`), Microsoft PowerPoint (.pptx).

---

### Task 1: Create PowerPoint Automation Script

**Files:**
- Create: `scratch/generate_presentation.py`

**Step 1: Write the python script containing the slide generator**

Create the python script at `scratch/generate_presentation.py` that implements the 15 detailed slides. The script uses inline dependencies for `python-pptx` and leverages the slide-building API.

**Step 2: Run the script to generate the slide deck**

Run the command: `uv run scratch/generate_presentation.py`
Expected output: PowerPoint compiles cleanly with exit code 0 and outputs the presentation at `ANCS_Agent_Graduation_Presentation.pptx`.

**Step 3: Commit**

```bash
git add scratch/generate_presentation.py
git commit -m "feat: add automated graduation presentation generator"
```

---

### Task 2: Verify Presentation Compilation & Output

**Files:**
- Test: Check that `ANCS_Agent_Graduation_Presentation.pptx` is generated.

**Step 1: Verify file existence and size**

Verify that `ANCS_Agent_Graduation_Presentation.pptx` exists in the root directory and contains significant bytes.

**Step 2: Commit**

```bash
git commit -m "docs: generate graduation presentation for ANCS AI Agent"
```
