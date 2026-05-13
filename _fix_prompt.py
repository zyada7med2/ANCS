"""Remove the orphaned duplicate system prompt text from ai_agent.py."""

FILEPATH = "network_manager/ai_agent.py"

with open(FILEPATH, "r", encoding="utf-8") as f:
    lines = f.readlines()

# Find the line that ends the NEW prompt (contains our closing triple-quote)
# Then find the next line that starts the COPILOT WORKER section
new_prompt_end = None
worker_start = None

for i, line in enumerate(lines):
    # The new prompt ends with: ...they asked."""
    if 'Respond directly to what they asked."""' in line and new_prompt_end is None:
        new_prompt_end = i
    # The worker section starts with the separator line
    if "COPILOT WORKER" in line and worker_start is None:
        worker_start = i - 1  # include the separator line above it

print(f"New prompt ends at line {new_prompt_end + 1}")
print(f"Worker section starts at line {worker_start + 1}")

if new_prompt_end is not None and worker_start is not None:
    # Keep everything up to and including the prompt end line,
    # then skip to the worker section
    orphan_count = worker_start - new_prompt_end - 1
    print(f"Removing {orphan_count} orphaned lines ({new_prompt_end + 2} to {worker_start})")
    
    new_lines = lines[:new_prompt_end + 1] + ["\n", "\n"] + lines[worker_start:]
    
    with open(FILEPATH, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    
    print("DONE")
else:
    print("ERROR: Could not find markers")
