# THS 512 Sector Full Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Audit all 512 THS software level-1 sectors against the proposed unified research schema and produce machine-readable findings plus a visually verified Chinese Word report.

**Architecture:** A read-only audit script joins the exported sector universe and constituent snapshot with local index, stock and valuation Parquet stores. A separate document builder consumes only the audit outputs, so calculations remain reproducible and Word layout changes cannot alter audit results.

**Tech Stack:** Python 3.10, pandas, DuckDB, Parquet, python-docx, LibreOffice renderer.

---

### Task 1: Full-sector audit

**Files:**
- Create: `temp/ths512_full_audit/audit_ths512.py`
- Create: `temp/ths512_full_audit/sector_audit.parquet`
- Create: `temp/ths512_full_audit/issue_register.parquet`
- Create: `temp/ths512_full_audit/audit_summary.json`

- [ ] Load the 512-sector export and the level-1 constituent snapshot.
- [ ] Compute index history, timeliness and 5/20/60/250-day technical statistics.
- [ ] Compute constituent market/valuation coverage and breadth statistics.
- [ ] Infer a provisional `sector_type` and apply deterministic issue rules.
- [ ] Write UTF-8 CSV, Parquet and JSON outputs and assert all 512 sectors are present.

### Task 2: Word report

**Files:**
- Create: `temp/ths512_full_audit/build_audit_report.py`
- Create: `temp/同花顺512板块统一研究模板全量问题报告.docx`

- [ ] Build a Chinese report using the `compact_reference_guide` preset.
- [ ] Include executive conclusions, issue counts, prefix/type distributions, priority actions and a complete 512-sector appendix.
- [ ] Render the DOCX to page PNGs with the bundled document renderer.
- [ ] Inspect every page and revise any overflow, clipping or bad page breaks.

