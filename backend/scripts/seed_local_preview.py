"""Add a clearly-labelled, separate workspace for local UI validation.

Never runs automatically. Refuses production. Prints only a credentials-file
path; generated credentials are local and ignored by source control.
"""
import json
import secrets
import sys
import uuid
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import config, db
from app.core.security import hash_password, hash_token
from app.models.models import User, Workspace, WorkspaceMember, Integration, Workflow, Execution
from app.modules import pipeline

if config.settings.app_env != "development":
    raise SystemExit("Preview fixtures are restricted to development.")
root = Path(__file__).resolve().parents[2]
credentials = root / ".local" / "preview-credentials.json"
if credentials.exists():
    raise SystemExit("Preview credentials already exist; no data changed.")
password = secrets.token_urlsafe(24)
email = "preview-" + uuid.uuid4().hex[:8] + "@example.com"
now = db.utcnow()
with db.get_session_factory()() as session:
    user = User(email=email, password_hash=hash_password(password), display_name="Local preview")
    session.add(user)
    session.flush()
    workspace = Workspace(name="Local preview · Sample data", slug="preview-" + uuid.uuid4().hex[:8], created_by=user.id)
    session.add(workspace)
    session.flush()
    session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
    integration = Integration(workspace_id=workspace.id, provider="n8n", name="n8n · Local fixture",
        enabled=False, status="pending", capabilities={}, ingest_token_hash=hash_token(secrets.token_urlsafe(32)))
    session.add(integration)
    session.flush()
    names = ["Invoice processing", "Lead enrichment", "Daily reporting", "Customer onboarding",
        "Inventory sync", "Support ticket routing", "CRM contact sync", "Payment reconciliation"]
    workflows = []
    for index, name in enumerate(names):
        workflow = Workflow(workspace_id=workspace.id, integration_id=integration.id,
            external_id=f"preview-{index}", name=name, environment="production", is_active=True,
            criticality="high" if index < 2 else "normal", last_synced_at=now)
        session.add(workflow)
        workflows.append(workflow)
    session.flush()
    for index in range(192):
        wf = workflows[index % len(workflows)]
        started = now - timedelta(minutes=7 * (192-index))
        failed = index in (168, 177, 184, 185)
        execution = Execution(workspace_id=workspace.id, workflow_id=wf.id, external_id=str(8400+index),
            status="failed" if failed else "success", started_at=started,
            finished_at=started+timedelta(seconds=2), duration_ms=1430+(index*137)%3000,
            failed_node="Payment API" if failed else None, error_class="TimeoutError" if failed else None,
            error_message_redacted="Payment API timed out after 30 seconds." if failed else None)
        session.add(execution)
        session.flush()
        if failed:
            pipeline.classify_incident(session, workspace_id=workspace.id, integration=integration,
                workflow=wf, execution=execution, error_message=execution.error_message_redacted,
                error_class=execution.error_class, failed_node=execution.failed_node)
    session.commit()
    record = {"email": email, "password": password, "workspace_id": str(workspace.id),
        "purpose": "Local UI validation only; all workflow and execution data in this workspace is synthetic."}
credentials.parent.mkdir(exist_ok=True)
credentials.write_text(json.dumps(record, indent=2), encoding="utf-8")
print("Local preview created. Credentials: " + str(credentials))
