# Working on Tilt

## Ending a session

Every coding session ends with a written handover, in this order:

1. **What was done** — briefly, and only what actually landed.
2. **Bugs found and issues filed** — with numbers, and whether each is fixed or open.
3. **Your tasks** — what needs a human, and specifically what needs a Mac or a
   real API key, since neither exists in this environment.
4. **What I can do next** — concrete, picked up without further briefing.
5. **Next stage in the plan** — where the roadmap now stands.
6. **Suggestions and alternatives** — including things worth *not* doing.

State plainly whether a branch is finished or has more coming. A pull request
that is done and a pull request that is mid-flight look identical from outside.

## House rules

- **No attribution to any AI author** anywhere in the repository — not in
  commits, pull request bodies, comments, code, or documentation.
- **This is not a productivity app.** No to-do lists, no kanban, no task
  extraction. The purpose is distilling thoughts, and features that turn the
  journal into a queue are the ones to argue against hardest.
- **Markdown is the record; SQLite is a cache.** Anything that only exists in
  `index.db` is something a documented, encouraged operation can destroy.
- **Prove a fix bites by reverting it** and watching a test go red. A test that
  passes before the change is not testing the change.
- **Measure before choosing a constant**, and write the measurement into the
  docstring rather than the conclusion.
