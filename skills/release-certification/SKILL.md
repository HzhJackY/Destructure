---
name: release-certification
description: Certify an AXA_research software release using layered tests, real-PDF evidence, production-like state, UI journeys, restart validation, and independent QA.
---

# Preconditions

Read all project context, rules, architecture, contracts, Golden governance, ADRs, incidents, and startup protocol.

# Release evidence layers

Report separately:

- unit tests;
- domain contracts;
- state-machine tests;
- defect invariants;
- synthetic fixtures;
- real-PDF service tests;
- production-like DATA_HOME;
- user journeys;
- process restart;
- independent QA;
- evidence-package completeness.

# Forbidden

- do not equate implementation completion with release completion;
- do not accept script existence as user-journey execution;
- do not accept report generation as evidence;
- do not let current actual define expected;
- do not certify with NOT_RUN gates.

# Completion

Return COMPLETE only when every blocking gate is supported by execution evidence.

Otherwise return BLOCKED.
