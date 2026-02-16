# Webhook Runbook Drills

## Objective

Operationalize `docs/WEBHOOK_INCIDENT_RUNBOOK.md` by running repeatable drills with clear ownership, timing, and pass/fail criteria.

## Roles

- **Incident Commander (IC)**: owns scope, timeline, decision points.
- **Operator**: executes list/replay/reconciliation commands.
- **Observer/Recorder**: captures timestamps, outcomes, gaps, follow-ups.
- **Reviewer**: signs off after post-drill review (typically engineering lead).

Minimum staffing per drill: IC + Operator + Observer.

## Cadence

- Weekly: one tabletop drill (no writes, dry-run workflows).
- Bi-weekly: one live-sim drill in non-prod.
- Monthly: one controlled prod-safe drill (single-event replay only, low-risk tenant window).

## Drill Scenarios

1. **Single Event Recovery**
- Simulate one missed reply event.
- Execute single-event replay.
- Verify lead/message state convergence.

2. **Window Replay Recovery**
- Simulate burst failure window.
- Execute replay-query with bounded limit.
- Verify replay counts and no residual mismatch.

3. **Provider Endpoint Degradation**
- Simulate provider transient errors.
- Validate taxonomy behavior (`transient`/`terminal`) and operator decisioning.

4. **Reconciliation Follow-up**
- After replay, run scoped reconciliation.
- Verify no additional errors and consistent local state.

## Pass/Fail Criteria

A drill is **pass** only if all are true:
- Correct endpoint sequence followed (list -> inspect -> replay -> verify).
- `X-Request-ID` present and captured in notes.
- Replay responses match expected counts/statuses.
- Local campaign/lead/message state matches expected post-replay state.
- Post-drill summary includes at least one concrete improvement action or explicit “no gaps”.

Any missed condition => **fail** and requires follow-up task.

## Run Template

Use this template for every drill:

```markdown
## Drill Record
- Date:
- Environment:
- Scenario:
- IC:
- Operator:
- Observer:
- Request ID Prefix:

### Scope
- Provider:
- Org ID:
- Company ID:
- Time Window:

### Execution Log
1. List events command + result:
2. Inspect decision:
3. Replay command(s) + result:
4. Reconciliation command + result:
5. Verification checks:

### Outcome
- Pass/Fail:
- Key metrics (matched/replayed/not_found/errors):
- Gaps found:
- Follow-up owner:
- Follow-up due date:
```

## Immediate Next Drill

- Scenario: Single Event Recovery
- Environment: staging
- Owner: Engineering lead
- SLA: complete within 7 days
