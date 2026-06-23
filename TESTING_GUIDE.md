# Phase 1 Testing Guide

## Pre-Testing Checklist

Before running tests, ensure:
- [ ] GNS3 is running with at least 5-10 devices (ideally 20)
- [ ] ANCS application starts without errors
- [ ] Database is accessible
- [ ] Network connectivity to GNS3 devices works

---

## Test 1: Basic Functionality (No Regressions)

### 1.1 Application Startup
```
Expected: ANCS launches without errors
Steps:
1. Start ANCS
2. Check Copilot initializes
3. Verify no Python errors in console
```

**Result**: ✅ / ❌

---

### 1.2 Audit Network Tool
```
Expected: audit_network() returns same JSON structure as before
Steps:
1. Open Copilot
2. Ask: "Audit all devices for security issues"
3. Check Execution Logs for:
   - Single DB query (not N+1)
   - JSON output with findings
   - No database errors
```

**Check for**:
- ✅ Findings array populated
- ✅ Protocol map shows detected protocols
- ✅ No "N+1" queries in logs (should see 1 query, not 20)
- ✅ Execution completes without errors

**Result**: ✅ / ❌

---

### 1.3 Device Connection Resolution
```
Expected: _resolve_device_connection() works with saved credentials
Steps:
1. In Copilot, ask: "Run 'show version' on [device_name]"
2. Check Execution Logs for:
   - Device connects successfully
   - Command executes
   - Output returned
```

**Check for**:
- ✅ Device connects (no "no host/credentials" error)
- ✅ Command output appears
- ✅ No database locking issues

**Result**: ✅ / ❌

---

### 1.4 GNS3 Tools
```
Expected: GNS3 tools work with singleton connector
Steps:
1. In Copilot, ask: "List all GNS3 nodes in this project"
2. Check Execution Logs for:
   - Nodes returned
   - No import errors
   - Connector reused (not recreated)
```

**Check for**:
- ✅ Nodes list populated
- ✅ No "GNS3Connector" instantiation errors
- ✅ JSON output valid

**Result**: ✅ / ❌

---

### 1.5 Config Parsing
```
Expected: Parser produces same output with pre-compiled patterns
Steps:
1. Pull a config from a device (Guided Setup → Live Sync)
2. Check parsed output:
   - VLANs detected
   - Routing protocol identified
   - Interfaces parsed
```

**Check for**:
- ✅ Same number of VLANs as before
- ✅ Routing protocol correctly identified
- ✅ No parsing errors

**Result**: ✅ / ❌

---

## Test 2: Performance Measurements

### 2.1 Audit Performance (N+1 Fix)

**Setup**: Have 20 devices in GNS3 with configs deployed

**Test**:
```
1. Open Copilot
2. Ask: "Audit all devices for security issues"
3. Time the execution (check Execution Logs timestamps)
4. Record: Start time → End time
```

**Expected**:
- Before: ~30 seconds
- After: ~5 seconds
- **Target**: 6x faster

**Measurement**:
```
Start: [timestamp]
End: [timestamp]
Duration: ___ seconds
Speedup: ___ x
```

**Result**: ✅ / ❌ (Pass if < 10 seconds)

---

### 2.2 Device Connection Performance (N+1 Fix)

**Setup**: Have 5 devices with saved credentials

**Test**:
```
1. Open Copilot
2. Ask: "Run 'show ip interface brief' on [device_name]"
3. Time the execution
4. Repeat 3 times, average the time
```

**Expected**:
- Before: ~10 seconds
- After: ~5 seconds
- **Target**: 2x faster

**Measurement**:
```
Run 1: ___ seconds
Run 2: ___ seconds
Run 3: ___ seconds
Average: ___ seconds
Speedup: ___ x
```

**Result**: ✅ / ❌ (Pass if < 8 seconds)

---

### 2.3 Config Parsing Performance (Regex Optimization)

**Setup**: Have a 50+ KB config file

**Test**:
```
1. In Guided Setup, click "Live Sync" on a device
2. Time the config pull + parsing
3. Check Execution Logs for parse time
```

**Expected**:
- Before: ~2 seconds
- After: ~600ms
- **Target**: 3x faster

**Measurement**:
```
Pull + Parse time: ___ seconds
Speedup: ___ x
```

**Result**: ✅ / ❌ (Pass if < 1.5 seconds)

---

### 2.4 Message History Size (Truncation)

**Setup**: Run a long conversation with Copilot

**Test**:
```
1. Open Copilot
2. Run 20+ tool calls (ask multiple questions)
3. Check memory usage or message history size
```

**Expected**:
- Before: ~10 MB after 100 turns
- After: ~5 MB after 100 turns
- **Target**: 50% smaller

**Measurement**:
```
After 20 tool calls: ___ MB
After 50 tool calls: ___ MB
Reduction: ___ %
```

**Result**: ✅ / ❌ (Pass if < 50% of original)

---

## Test 3: Regression Testing

### 3.1 Database Integrity
```
Expected: No database corruption or locking issues
Steps:
1. Run audit_network() 3 times in succession
2. Check for database errors in logs
3. Verify data consistency
```

**Check for**:
- ✅ No "database is locked" errors
- ✅ Same results on repeated runs
- ✅ No data corruption

**Result**: ✅ / ❌

---

### 3.2 Tool Output Consistency
```
Expected: Same tool outputs before and after changes
Steps:
1. Run each tool 2 times
2. Compare outputs
3. Verify identical results
```

**Tools to test**:
- [ ] list_gns3_projects()
- [ ] list_gns3_nodes()
- [ ] list_all_devices()
- [ ] audit_network()
- [ ] trace_connectivity()
- [ ] generate_device_config()

**Result**: ✅ / ❌

---

### 3.3 Deployment Still Works
```
Expected: Config deployment unchanged
Steps:
1. Generate a config via Copilot
2. Deploy to a device
3. Verify deployment succeeds
4. Check device has new config
```

**Check for**:
- ✅ Config deploys without errors
- ✅ Device receives config
- ✅ Hostname/settings applied

**Result**: ✅ / ❌

---

## Test 4: Edge Cases

### 4.1 Empty Database
```
Expected: Tools handle empty device list gracefully
Steps:
1. Temporarily remove all devices from database
2. Run audit_network()
3. Check for proper error message
```

**Result**: ✅ / ❌

---

### 4.2 Large Config Files
```
Expected: Parser handles 100+ KB configs
Steps:
1. Find or create a large config (100+ KB)
2. Parse it via Live Sync
3. Check for timeouts or errors
```

**Result**: ✅ / ❌

---

### 4.3 Missing Credentials
```
Expected: Device connection handles missing credentials
Steps:
1. Remove credentials for a device
2. Try to run CLI command on it
3. Check for proper error message
```

**Result**: ✅ / ❌

---

## Summary Report Template

```
# Phase 1 Testing Report

**Date**: ___________
**Tester**: ___________
**GNS3 Devices**: _____ (count)

## Functionality Tests
- [ ] Application Startup: ✅ / ❌
- [ ] Audit Network: ✅ / ❌
- [ ] Device Connection: ✅ / ❌
- [ ] GNS3 Tools: ✅ / ❌
- [ ] Config Parsing: ✅ / ❌

## Performance Tests
- [ ] Audit (target: 6x faster): ✅ / ❌ — ___ seconds
- [ ] Device Connection (target: 2x faster): ✅ / ❌ — ___ seconds
- [ ] Config Parsing (target: 3x faster): ✅ / ❌ — ___ seconds
- [ ] Message History (target: 50% smaller): ✅ / ❌ — ___ MB

## Regression Tests
- [ ] Database Integrity: ✅ / ❌
- [ ] Tool Output Consistency: ✅ / ❌
- [ ] Deployment Works: ✅ / ❌

## Edge Cases
- [ ] Empty Database: ✅ / ❌
- [ ] Large Configs: ✅ / ❌
- [ ] Missing Credentials: ✅ / ❌

## Issues Found
1. ___________
2. ___________
3. ___________

## Overall Result
✅ PASS / ❌ FAIL

## Notes
___________
```

---

## How to Run Tests

### Option 1: Manual Testing (Recommended First)
1. Start ANCS
2. Open Copilot
3. Follow Test 1 (Functionality) step by step
4. Record results

### Option 2: Automated Testing (If you have pytest)
```bash
# Run basic syntax check
python -m py_compile network_manager/ai_agent.py
python -m py_compile network_manager/network/parser.py

# Run unit tests (if available)
pytest tests/ -v
```

### Option 3: Performance Profiling
```bash
# Add timing to Copilot logs
# Check Execution Logs for [Tool Result] timestamps
# Calculate duration between tool calls
```

---

## What to Look For

### ✅ Signs of Success
- Audit completes in < 10 seconds (was ~30s)
- Device commands execute in < 8 seconds (was ~10s)
- Config parsing in < 1.5 seconds (was ~2s)
- No database errors
- Same tool outputs as before

### ❌ Signs of Problems
- Database locked errors
- Tool outputs different from before
- Slower than expected
- Memory usage growing unbounded
- Deployment failures

---

## Next Steps

**If all tests pass** ✅:
- Phase 1 is stable
- Ready for Phase 2 (optional)
- Document performance improvements

**If tests fail** ❌:
- Identify which test failed
- Check error messages in Execution Logs
- Report the issue with:
  - Test name
  - Expected vs actual result
  - Error message
  - Steps to reproduce

---
