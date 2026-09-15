<!-- SCC-OMP-SECTION -->
# SCC (System Context Compiler)
This repository is indexed by SCC. Durable rules:
- The native SCC extension injects the startup architecture once per session
and a task-specific context pack per prompt. Work within the injected task
context; it is the authoritative system slice for the current goal.
- For the fused startup architecture (Atlas + Surface + coverage),
`scc context startup` is the canonical command; `scc atlas` is only its
Level-0 Atlas component.
- Authority ordering: source/runtime > SCC System IR > checkpoint > Hindsight
> model assumption.
- Drift and invariants: `scc drift`, `scc ci check`, and `scc impact <files>`
before cross-layer edits.
<!-- /SCC-OMP-SECTION -->
