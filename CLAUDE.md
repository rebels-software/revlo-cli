# Concierge Project

This project uses Concierge for multi-agent orchestration.

## Plan Mode

When using plan mode, save all plans to `.claude/plans/` with the naming convention:
```
.claude/plans/plan_XX_short-name.md
```

Where XX is a zero-padded sequence number (01, 02, 03...) and short-name describes the plan.

Example: `.claude/plans/plan_01_auth-system.md`

## Project Files

- `AGENTS.md` - Project context and development commands
- `prd.json` - User stories and acceptance criteria
- `progress.txt` - Completed work log
- `.claude/agents/` - Specialist agent definitions
- `.claude/plans/` - Implementation plans
- `.concierge/handoffs/` - Agent handoff files
