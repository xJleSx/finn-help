---
description: Run code review on a file, PR, or module. Delegates to the finn-reviewer subagent.
---

Delegate to `finn-reviewer` subagent via the `task` tool with:

```
task /finn-reviewer "Review $ARGUMENTS"
```

If the user did not specify what to review, ask for a file path, diff, or module name. Review for: type safety, error handling, async correctness, security, missing tests, N+1 queries, project conventions.
