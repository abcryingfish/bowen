# Dual Account Order State Machine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace blocking盘口追单 in the ordinary and credit account GBK scripts with a persistent, cross-timer order state machine that safely handles partial fills.

**Architecture:** Each account script keeps its own implementation and account-specific submission/cancellation rules. A response row is the durable parent execution record; timer callbacks reconcile one active child order, persist cumulative fill deltas, and only submit the next child after the previous child reaches a terminal state.

**Tech Stack:** Python, pandas, QMT strategy APIs, GBK text files, pytest/static AST checks.

---

### Task 1: Add executable state-model tests

**Files:**
- Create: `test_dual_account_order_state_machine.py`
- Test: `C:/Users/Administrator/Desktop/普通账户_修复版_GBK.txt`
- Test: `C:/Users/Administrator/Desktop/两融账户_修复版_GBK.txt`

- [ ] Write tests that decode both files as GBK, parse them as Python, verify the response state columns, and exercise pure helpers for cumulative-fill deltas, terminal gating, lot sizing, and half-sell remaining volume.
- [ ] Run `.venv\Scripts\python.exe -m pytest test_dual_account_order_state_machine.py -q` and confirm the new structural tests fail before implementation.

### Task 2: Implement ordinary-account state persistence

**Files:**
- Modify: `C:/Users/Administrator/Desktop/普通账户_修复版_GBK.txt`

- [ ] Extend response columns with execution stage, active order fields, target fields, tick/round counters, cumulative amount, cancel metadata, and state timestamp.
- [ ] Add legacy response migration so existing 13/14-column files load with empty state fields.
- [ ] Add row-update and atomic-save helpers; persist after every fill delta and state transition.
- [ ] Add restart reconciliation and pending-stock blocking from response state.

### Task 3: Implement ordinary-account timer state machine

**Files:**
- Modify: `C:/Users/Administrator/Desktop/普通账户_修复版_GBK.txt`

- [ ] Change initial order handling to submit at most one child order and return immediately.
- [ ] On each timer, count one new quote tick, reconcile cumulative fill delta, request cancellation once after two ticks, and wait indefinitely for terminal state without sleeping.
- [ ] After terminal state, recompute remaining target, re-read best quote and available position, enforce lot/odd-lot, slippage, limit-price, round and close-time guards, then submit at most one next child.
- [ ] Keep half-sell target fixed and update its persisted progress only by newly confirmed fill deltas.

### Task 4: Implement credit-account state machine independently

**Files:**
- Modify: `C:/Users/Administrator/Desktop/两融账户_修复版_GBK.txt`

- [ ] Copy the validated state pattern into the credit script without importing the ordinary script.
- [ ] Preserve credit buy-direction selection, financing/collateral counters, sell-repayment direction, credit availability checks, and order-sysid-first cancellation.
- [ ] Apply the same two-tick, one-cancel, terminal-gated retry, partial-fill delta and persistence rules.

### Task 5: Verify encoding and behavior

**Files:**
- Test: `test_dual_account_order_state_machine.py`

- [ ] Run the focused pytest suite and confirm all scenarios pass.
- [ ] Decode and re-encode each output with strict GBK and confirm byte-stable round trips.
- [ ] Compile decoded source with `compile(source, filename, 'exec')` for both scripts.
- [ ] Search the state-advance functions for `sleep` and `wait_market_ticks`; confirm neither is present.
- [ ] Verify ordinary and credit response prefixes, account IDs, trade directions, and cancellation APIs remain distinct.
