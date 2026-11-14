# Definition of Done

A feature is done only when all applicable items are complete:

- [ ] Acceptance criteria are explicit and verified.
- [ ] Request/response schemas and API documentation are updated.
- [ ] Authorization and tenant/resource ownership are enforced server-side.
- [ ] Failure, timeout, cancellation, and concurrency behavior is specified.
- [ ] Unit tests cover domain rules and edge cases.
- [ ] Integration/contract tests cover external boundaries.
- [ ] Migrations are reversible or have a documented forward-recovery path.
- [ ] Ruff and static type checks pass.
- [ ] Logs, metrics, and traces are updated without sensitive content leakage.
- [ ] Secrets and personal data are handled according to policy.
- [ ] Developer and operator documentation is updated.
- [ ] CI checks pass and at least one code review is completed.

A green local happy-path demo alone does not satisfy the definition of done.
