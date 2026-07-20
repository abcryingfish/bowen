# Exclude BJ From Sector Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve raw THS constituents while excluding all `.BJ` securities from sector analytics and reports.

**Architecture:** A deterministic market-scope function separates source constituents from eligible SH/SZ constituents before any market or valuation join. Audit outputs retain source, excluded and eligible counts so the filtering rule remains visible and testable.

**Tech Stack:** Python, pandas, DuckDB, pytest, Parquet, python-docx.

---

### Task 1: Market-scope regression test

**Files:**
- Create: `temp/ths512_full_audit/test_audit_ths512.py`
- Modify: `temp/ths512_full_audit/audit_ths512.py`

- [ ] Write a failing test proving `.BJ` is excluded while SH/SZ and source counts remain intact.
- [ ] Add the minimal market-scope function.
- [ ] Run the focused test and confirm it passes.

### Task 2: Full audit and report rebuild

**Files:**
- Modify: `temp/ths512_full_audit/audit_ths512.py`
- Modify: `temp/ths512_full_audit/build_audit_report.py`
- Regenerate: `temp/ths512_full_audit/sector_audit.parquet`
- Regenerate: `temp/ths512_full_audit/issue_register.parquet`
- Regenerate: `temp/同花顺512板块统一研究模板全量问题报告.docx`

- [ ] Apply the filter before stock and valuation calculations.
- [ ] Re-run all 512 sectors and verify count identities and zero `.BJ` eligible members.
- [ ] Update report wording and tables to disclose the analysis scope.
- [ ] Render and visually inspect the final Word report.

