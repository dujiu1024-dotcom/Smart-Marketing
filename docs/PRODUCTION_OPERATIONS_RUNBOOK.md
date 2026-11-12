# Production Operations Runbook

> Scope: API, PostgreSQL, Redis, Celery Worker/Scheduler, private object storage and channel delivery.
> This runbook describes executable procedures; it is not evidence that a production restore or rollback has already been performed.

## 1. Pre-deployment checks

1. Confirm the target release commit and review its migrations.
2. Confirm production .env values, especially ENVIRONMENT=production, the session token pepper, HTTPS object-storage public endpoint, bucket and credentials.
3. Confirm the private object-storage bucket policy and backup retention/encryption policy outside the application host.
4. Take a database backup before applying migrations.
5. Confirm an operator alert receiver is configured if webhook notifications are required.

## 2. PostgreSQL backup

Run from the repository root with the production Compose project available:

\`\`\`bash
BACKUP_DIR=/secure/backups/smart-marketing \\
  bash scripts/backup-postgres.sh
\`\`\`

To choose an exact path:

\`\`\`bash
BACKUP_DIR=/secure/backups/smart-marketing \\
BACKUP_FILE=/secure/backups/smart-marketing/store_operator_predeploy.dump \\
  bash scripts/backup-postgres.sh
\`\`\`

The script uses PostgreSQL custom format, sets the backup directory to mode 0700 and the dump file to mode 0600, and fails if the dump is empty. Copy the backup to the approved encrypted off-host backup location and verify the copy before migration. Do not store production backups in Git or public object storage.

## 3. Restore (destructive)

**Restore replaces database objects in the target database. Verify the target and backup before proceeding.**

1. Stop API, Worker and Scheduler services to prevent concurrent writes.
2. Verify the backup file exists, is non-empty, and belongs to the intended environment.
3. Run the restore with the explicit destructive confirmation:

\`\`\`bash
BACKUP_FILE=/secure/backups/smart-marketing/store_operator_predeploy.dump \\
CONFIRM_RESTORE=YES \\
  bash scripts/restore-postgres.sh
\`\`\`

4. Start services and verify API liveness/readiness, worker health, representative store-scoped reads and job processing.
5. Record the operator, timestamp, source backup, target database and verification result in the release/incident record.

The restore script refuses to run unless CONFIRM_RESTORE=YES is present. Do not use a backup from another environment.

## 4. Deploy and migrate

From the checked-out release commit:

\`\`\`bash
uv sync --locked --directory apps/api
uv run --locked --directory apps/api alembic upgrade head
POSTGRES_PASSWORD="$POSTGRES_PASSWORD" docker compose -f infra/compose/docker-compose.yml up --build --detach --wait
curl --fail --silent --show-error http://localhost:8000/health/live
curl --fail --silent --show-error http://localhost:8000/health/ready
curl --fail --silent --show-error http://localhost:5173/ >/dev/null
\`\`\`

Check Worker and Scheduler container health and confirm no growing queue backlog or dead Outbox events. Do not run a migration from an unreviewed branch.

## 5. Rollback

- Prefer rolling back the application image/code while keeping the database schema if the migration is backward-compatible.
- Do not run alembic downgrade in production as an automatic rollback. Review each downgrade for data loss and compatibility first.
- If the schema or data must be restored, stop all writers and use the explicit database restore procedure above with an approved pre-change backup.
- After rollback, verify health endpoints, store isolation, queued/running jobs, object access and channel-operation states.
- If an external publish side effect is unknown, do not retry automatically. Read back the platform state or require operator reconciliation first.

## 6. Operational alerts

Set OPS_ALERT_WEBHOOK_URL in the Worker/Scheduler environment to receive sanitized JSON POST alerts. If it is unset, the Worker still emits structured ops.alert log events for a log-based alert pipeline.

| Alert event | Trigger | Initial response |
|---|---|---|
| provider.failure | AI Provider execution fails | Check provider availability, safe error code and retry policy; inspect usage/attempt history |
| channel.delivery.failure | Channel/publish job fails | Check account authorization and platform response; read back before retrying |
| job.execution.failure | Domain job fails | Inspect job type, attempt history and safe error code |
| job.timeout | Job exceeds configured timeout | Check provider latency and whether an external side effect may have occurred |
| worker.unexpected_failure | Unexpected Worker exception | Inspect sanitized logs and job attempt; reconcile unknown side effects |
| worker.expired_leases_recovered | Expired Worker leases recovered | Check Worker restart/heartbeat health and manually reconcile affected jobs |
| outbox.dead_letter | Outbox dispatch reaches retry limit | Inspect broker connectivity and re-dispatch only after confirming event/job state |
| job.handler_missing | No handler registered for a persisted job type | Check release compatibility and Worker registry |

Alerts include a correlation ID and sanitized attributes. Webhook delivery has a short timeout and cannot fail the underlying job. Delivery failures are logged as ops.alert_delivery_failed; configure receiver availability and escalation in the external alerting system.

### Dead-letter Outbox recovery

Only replay a dead event after the broker/transport incident is resolved and the referenced job is confirmed to remain in `queued` or `retry_wait`. The command refuses non-dispatch events, terminal/running jobs, missing events and a mismatched confirmation ID. It resets the dispatch retry counter, preserves the original event ID/dedupe key, and writes an audit event with the previous attempt count and operator reason.

```bash
PYTHONPATH=src uv run --locked --directory apps/api python -m store_operator.cli replay-dead-outbox \
  --event-id <OUTBOX_EVENT_UUID> \
  --reason "Broker recovered; verified job is still queued" \
  --confirm-event-id <SAME_OUTBOX_EVENT_UUID>
```

Do not replay a dispatch event when the job is running, succeeded, failed, cancelled or awaiting human reconciliation. For unknown external side effects, reconcile the provider/platform state first; Outbox replay only re-enqueues the job and does not authorize repeating an external side effect.

## 7. Recovery and fault-injection evidence

- API CI runs real PostgreSQL migrations up/down/up and the API test suite.
- Worker CI runs lease fencing, expired-lease recovery, retry, cancellation, dead-letter-related service rules and unknown-side-effect tests.
- Infrastructure CI starts the Compose stack, verifies readiness and volume persistence, then performs a backup → mutate → restore → verify rehearsal.
- These CI checks are repeatable engineering evidence, not a production disaster-recovery drill. A production restore rehearsal, provider outage drill, broker outage drill and channel-side-effect reconciliation exercise must be recorded separately before production sign-off.
