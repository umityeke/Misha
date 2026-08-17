# Planner safety

Planner output is treated as untrusted data. Before execution Misha validates:

- maximum five steps and allowlisted tools;
- exact parameter and step-field schemas;
- unique positive step IDs;
- existing, non-self dependencies;
- absence of circular dependencies;
- stable topological execution order;
- absence of duplicate or already-completed tool calls;
- declared-goal overlap with the user's request;
- prohibition of web search as a fallback for local projects, files or IDE state;
- separation of conversational `respond` plans from executable tool plans.

The desktop receives a bounded preflight summary before the first tool runs.
Parameters are omitted from this summary. Steps that will need approval are
identified early, but this preview never grants authority: the executor still
requires exact, scope-bound approval immediately before each effectful action.

Invalid model output falls back to a safe local-error response and never to
generated code or an opportunistic web search.
