# 乳业研究流程边界修正 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 保留乳业Browser获取方法，同时消除并发发布、固定研究顺序和证据归档不可复核的问题。

**Architecture:** 独立顶层任务动态研究单一对象并只写隔离staging；主任务完成审计、正式发布和共享知识更新。Browser、Bing和正文阅读方法保持不变。

**Tech Stack:** Markdown流程契约、Codex Browser、JSON/Parquet证据存储。

---

### Task 1: 写入职责

- [x] 用失败断言确认旧Skill缺少共享状态串行发布限制。
- [x] 规定独立任务不得直接更新共享档案和知识库。

### Task 2: 动态研究循环

- [x] 用失败断言确认旧Skill把乳业12轮误写为固定顺序。
- [x] 将12轮改为乳业事实示例，以专属研究问题和连续两轮饱和为停止条件。

### Task 3: 证据归档

- [x] 用失败断言确认旧Skill缺少正文访问级别。
- [x] 增加 `access_level`、原始内容路径和原始内容哈希要求。
- [x] 运行全新执行者的契约理解回归测试。
- [x] 运行UTF-8、Skill格式和共享写入冲突扫描。
