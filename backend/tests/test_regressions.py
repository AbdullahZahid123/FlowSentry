import uuid
from datetime import timedelta
from urllib.parse import urlsplit, parse_qs

import httpx
import pytest
from sqlalchemy import select, func

from app.core import config, db, egress
from app.core.errors import ApiError
from app.core.pagination import encode_cursor, decode_cursor
from app.core.redaction import redact_string, redact_value
from app.adapters.n8n.adapter import N8nAdapter
from app.adapters.base import NormalizedPage, NormalizedExecution
from app.models.models import (Execution, Incident, InboundEvent, Integration, Notification,
    NotificationAttempt, Workflow, SyncCursor, AlertRule, AlertRuleChannel, NotificationChannel)
from app.modules import pipeline
from app.modules.notifications import validate_conditions
from app import worker


def connect(client, owner):
    params, headers = owner
    response = client.post("/integrations", params=params, headers=headers,
        json={"name": "Local n8n", "provider": "n8n"})
    assert response.status_code == 201, response.text
    return response.json()["data"]


def send_failure(client, integration, execution="100", workflow="wf1"):
    return client.post(f"/ingest/{integration['id']}/n8n",
        headers={"Authorization": "Bearer " + integration["ingress_token_once"]},
        json={"workflow": {"id": workflow, "name": "Invoice processing"},
            "execution": {"id": execution, "lastNodeExecuted": "Payment API",
                "error": {"name": "TimeoutError", "message": "Payment API timeout"}}})


def test_webhook_durable_deduplicated_and_incident_actions(client, owner):
    params, headers = owner
    integration = connect(client, owner)
    first = send_failure(client, integration)
    assert first.status_code == 200, first.text
    assert first.json()["data"]["duplicate"] is False
    again = send_failure(client, integration)
    assert again.json()["data"]["event_id"] == first.json()["data"]["event_id"]
    assert again.json()["data"]["duplicate"] is True
    assert worker.drain_outbox_once() >= 1
    with db.get_session_factory()() as session:
        event = session.get(InboundEvent, uuid.UUID(first.json()["data"]["event_id"]))
        assert event.processing_status == "processed"
        pipeline.process_inbound_event(session, event)
        session.commit()
    incidents = client.get("/incidents", params=params).json()["data"]
    assert len(incidents) == 1 and incidents[0]["occurrence_count"] == 1
    incident_id = incidents[0]["id"]
    assert client.post(f"/incidents/{incident_id}/acknowledge", params=params, headers=headers).status_code == 200
    assert client.post(f"/incidents/{incident_id}/comments", params=params, headers=headers,
        json={"body": "Investigating the payment provider."}).status_code == 201
    timeline = client.get(f"/incidents/{incident_id}/timeline", params=params).json()["data"]
    assert any(x["message"] == "Investigating the payment provider." for x in timeline)
    assert client.post(f"/incidents/{incident_id}/resolve", params=params, headers=headers,
        json={"resolution_note": "Provider recovered."}).status_code == 200
    metrics = client.get("/analytics/overview", params=params).json()["data"]
    assert metrics["failed_executions"] == 1  # no startedAt still counts


def test_ingress_auth_validation_and_stream_size(client, owner, monkeypatch):
    integration = connect(client, owner)
    path = f"/ingest/{integration['id']}/n8n"
    assert client.post(path, json={}).status_code == 401
    headers = {"Authorization": "Bearer " + integration["ingress_token_once"]}
    assert client.post(path, headers=headers, json={}).status_code == 422
    monkeypatch.setattr(config.settings, "max_inbound_payload_bytes", 80)
    assert client.post(path, headers=headers, json={"x": "x" * 100}).status_code == 413


def test_csrf_and_workspace_isolation(client, owner):
    params, headers = owner
    integration = connect(client, owner)
    assert client.post("/integrations", params=params, json={"name": "blocked"}).status_code == 403
    other = {"workspace_id": str(uuid.uuid4())}
    assert client.get(f"/integrations/{integration['id']}", params=other).status_code == 404


def test_invitation_is_bound_to_email_and_viewer_cannot_write(client, owner):
    params, headers = owner
    response = client.post(f"/workspaces/{params['workspace_id']}/invitations", headers=headers,
        json={"email": f"invite-{uuid.uuid4().hex}@example.com", "role": "viewer"})
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    token = data.get("invitation_token_once") or data.get("token_once")
    if not token:
        token = parse_qs(urlsplit(data["invitation_url"]).query)["invite"][0]
    wrong = client.post("/auth/register", json={"email": "wrong@example.com", "password": "test-password-123", "invitation_token": token})
    assert wrong.status_code == 422
    accepted = client.post("/auth/register", json={"email": data["email"], "password": "test-password-123", "invitation_token": token})
    assert accepted.status_code == 201, accepted.text
    viewer_headers = {"X-CSRF-Token": client.cookies["flowsentry_csrf"]}
    assert client.get("/integrations", params=params).status_code == 200
    assert client.post("/integrations", params=params, headers=viewer_headers, json={"name": "blocked"}).status_code == 403


def test_execution_pagination_ties_and_missing_timestamps(client, owner):
    params, _ = owner
    integration = connect(client, owner)
    send_failure(client, integration)
    worker.drain_outbox_once()
    with db.get_session_factory()() as session:
        wf = session.execute(select(Workflow).where(Workflow.integration_id == uuid.UUID(integration["id"]))).scalar_one()
        now = db.utcnow()
        for number in range(6):
            session.add(Execution(workspace_id=wf.workspace_id, workflow_id=wf.id, external_id=f"page-{number}",
                status="success", started_at=now if number < 3 else None))
        session.commit()
    found = []
    cursor = None
    for _ in range(8):
        r = client.get("/executions", params={**params, "limit": 2, **({"cursor": cursor} if cursor else {})})
        assert r.status_code == 200, r.text
        found.extend(x["id"] for x in r.json()["data"])
        cursor = r.json()["meta"]["next_cursor"]
        if not cursor:
            break
    assert len(found) == len(set(found)) == 7
    assert client.get("/executions", params={**params, "cursor": "invalid"}).status_code == 422


def test_polling_idempotency_zero_duration_and_historical_success(client, owner):
    integration = connect(client, owner)
    now = db.utcnow()
    with db.get_session_factory()() as session:
        source = session.get(Integration, uuid.UUID(integration["id"]))
        cursor = SyncCursor(integration_id=source.id, resource_type="executions", next_poll_at=now)
        session.add(cursor)
        session.flush()
        item = NormalizedExecution(external_id="poll-1", status="failed", started_at=now,
            duration_ms=0, error_class="TimeoutError", error_message_redacted="Timeout",
            provider_metadata={"workflowId": "discovered"})
        worker._apply_sync_page(session, source, cursor, NormalizedPage([item]), now)
        session.commit()
        worker._apply_sync_page(session, source, cursor, NormalizedPage([item]), now)
        session.commit()
        incident = session.execute(select(Incident).where(Incident.integration_id == source.id)).scalar_one()
        assert incident.occurrence_count == 1
        execution = session.execute(select(Execution).where(Execution.workflow_id == incident.workflow_id)).scalar_one()
        assert execution.duration_ms == 0
        historical = NormalizedExecution(external_id="old-success", status="success", started_at=now-timedelta(days=1),
            provider_metadata={"workflowId": "discovered"})
        worker._apply_sync_page(session, source, cursor, NormalizedPage([historical]), now)
        assert incident.status == "open"


def test_analytics_buckets_respect_requested_width(client, owner):
    params, _ = owner
    result = client.get("/analytics/executions", params={**params, "window_hours": 24, "bucket_hours": 6})
    assert result.status_code == 200, result.text
    buckets = result.json()["data"]
    assert len(buckets) == 5
    assert all(x["success"] == x["failed"] == 0 for x in buckets)


def test_delivery_retry_and_expired_sending_lease(client, owner, monkeypatch):
    params, headers = owner
    response = client.post("/notification-channels", params=params, headers=headers,
        json={"name": "Local log", "channel_type": "log", "configuration": {}})
    assert response.status_code == 201, response.text
    channel = response.json()["data"]["id"]
    with db.get_session_factory()() as session:
        n = Notification(workspace_id=uuid.UUID(params["workspace_id"]), channel_id=uuid.UUID(channel),
            dedupe_key=str(uuid.uuid4()), body_redacted="Regression test", next_attempt_at=db.utcnow())
        session.add(n)
        session.commit()
        nid = n.id
    monkeypatch.setattr(worker, "send_notification_payload", lambda *args: (False, "simulated_failure"))
    worker.deliver_notifications_once()
    with db.get_session_factory()() as session:
        n = session.get(Notification, nid)
        assert n.status == "failed" and n.attempt_count == 1 and n.next_attempt_at is not None
        n.status = "sending"
        n.next_attempt_at = db.utcnow()-timedelta(seconds=1)
        session.commit()
    monkeypatch.setattr(worker, "send_notification_payload", lambda *args: (True, None))
    assert worker.deliver_notifications_once() >= 1
    with db.get_session_factory()() as session:
        n = session.get(Notification, nid)
        assert n.status == "delivered" and n.attempt_count == 2
    # Removing a channel must not break historical notification foreign keys.
    assert client.delete(f"/notification-channels/{channel}", params=params, headers=headers).status_code == 204
    assert client.get("/notifications", params=params).status_code == 200


@pytest.mark.parametrize("conditions", [{"failure_rate_gte": 2}, {"consecutive_failures_gte": True},
    {"consecutive_failures_gte": 1.5}, {"unknown": 1}])
def test_rule_condition_bounds(conditions):
    with pytest.raises(ApiError):
        validate_conditions(conditions)


def test_redaction_and_cursor_integrity():
    value = redact_string("password=hunter22 api_key=secretvalue user@example.com Bearer abcdefghijkl")
    assert not any(x in value for x in ["hunter22", "secretvalue", "user@example.com", "abcdefghijkl"])
    assert redact_value({"authorization": "abc"})["authorization"] == "[REDACTED]"
    cursor = encode_cursor({"k": str(uuid.uuid4()), "s": None})
    assert decode_cursor(cursor)["s"] is None
    with pytest.raises(ApiError):
        decode_cursor(cursor + "tampered")


def test_adapter_transmits_cursor_and_unknown_status(monkeypatch):
    import app.adapters.n8n.adapter as module
    requests = []
    def request(method, url, **kwargs):
        requests.append(url)
        return httpx.Response(200, json={"data": [], "nextCursor": "next"})
    monkeypatch.setattr(module.egress, "safe_request", request)
    N8nAdapter().list_executions("https://n8n.example.com", "secret", "opaque+/=", 25)
    assert parse_qs(urlsplit(requests[0]).query)["cursor"] == ["opaque+/="]
    assert N8nAdapter().normalize_execution_payload({"id": "1", "stoppedAt": "2026-11-03T00:00:00Z"}).status == "unknown"


def test_egress_rejects_private_and_redirects_and_pins_dns(monkeypatch):
    monkeypatch.setattr(egress.socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(egress.SsrfViolation):
        egress.resolve_url_and_validate("https://example.com", egress.EgressPolicy())
    monkeypatch.setattr(egress, "resolve_url_and_validate", lambda *a: ["93.184.216.34"])
    real_client = httpx.Client
    seen = []
    def handle(request):
        seen.append(request)
        return httpx.Response(200, content=b"ok")
    monkeypatch.setattr(egress.httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs))
    assert egress.safe_request("GET", "https://example.com/api").text == "ok"
    assert seen[0].url.host == "93.184.216.34" and seen[0].headers["host"] == "example.com"
    assert seen[0].extensions["sni_hostname"] == "example.com"
    with pytest.raises(egress.SsrfViolation):
        egress.safe_request("GET", "https://example.com/api", max_bytes=1)
    monkeypatch.setattr(egress.httpx, "Client", lambda **kwargs: real_client(
        transport=httpx.MockTransport(lambda r: httpx.Response(302, headers={"location": "https://evil.com"})), **kwargs))
    with pytest.raises(egress.SsrfViolation):
        egress.safe_request("GET", "https://example.com/api")


def test_production_requires_secrets_and_https():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        config.Settings(_env_file=None, app_env="production", app_secret_key="", encryption_key="")


def test_first_failure_alerts_and_cooldown_is_scoped_to_incident(client, owner):
    params, headers = owner
    integration = connect(client, owner)
    channel = client.post("/notification-channels", params=params, headers=headers,
        json={"name": "Regression log", "channel_type": "log", "configuration": {}}).json()["data"]["id"]
    response = client.post("/alert-rules", params=params, headers=headers,
        json={"name": "All failures", "event_types": ["execution.failed"], "channel_ids": [channel], "cooldown_seconds": 300})
    assert response.status_code == 201, response.text
    send_failure(client, integration, "first", "wf1")
    send_failure(client, integration, "other", "wf2")
    worker.drain_outbox_once()
    notifications = client.get("/notifications", params=params).json()["data"]
    assert len(notifications) == 2
    send_failure(client, integration, "again", "wf1")
    worker.drain_outbox_once()
    assert len(client.get("/notifications", params=params).json()["data"]) == 2


def test_source_events_are_scoped_to_integration(client, owner):
    params, _ = owner
    first, second = connect(client, owner), connect(client, owner)
    send_failure(client, first, "same-source-id")
    send_failure(client, second, "same-source-id")
    worker.drain_outbox_once()
    executions = client.get("/executions", params=params).json()["data"]
    assert len(executions) == 2
    for execution in executions:
        events = client.get(f"/executions/{execution['id']}/events", params=params).json()["data"]
        assert len(events) == 1


def test_workflow_health_includes_events_without_started_at_and_pagination(client, owner):
    params, _ = owner
    integration = connect(client, owner)
    for index in range(3):
        send_failure(client, integration, str(index), "wf" + str(index))
    worker.drain_outbox_once()
    page = client.get("/workflows", params={**params, "limit": 2})
    assert page.status_code == 200, page.text
    first = page.json()
    assert all(w["health"]["state"] == "critical" for w in first["data"])
    next_page = client.get("/workflows", params={**params, "limit": 2, "cursor": first["meta"]["next_cursor"]})
    assert next_page.status_code == 200, next_page.text
    assert len(next_page.json()["data"]) == 1
    health = client.get(f"/workflows/{first['data'][0]['id']}/health", params=params)
    assert health.status_code == 200 and health.json()["data"]["failure_count"] == 1
    incidents = client.get("/incidents", params={**params, "limit": 2}).json()
    assert client.get("/incidents", params={**params, "cursor": incidents["meta"]["next_cursor"]}).status_code == 200

def test_workflow_logic_keeps_branches_and_excludes_secrets():
    from app.modules.workflow_logic import extract_topology, build_logic_map
    raw={"nodes":[{"name":n,"type":"n8n-nodes-base.if" if n=="Check" else "n8n-nodes-base.set", "parameters":{"secret":"never-store"},"credentials":{"id":"private"}} for n in ["Start","Prepare","Check","Charge","Email","Merge"]],"connections":{
      "Start":{"main":[[{"node":"Prepare"}]]},"Prepare":{"main":[[{"node":"Check"}]]},"Check":{"main":[[{"node":"Charge"}],[{"node":"Email"}]]},"Charge":{"main":[[{"node":"Merge"}]]},"Email":{"main":[[{"node":"Merge"}]]}}}
    topology=extract_topology(raw)
    assert "never-store" not in str(topology) and "credentials" not in str(topology)
    logic=build_logic_map(topology)
    assert logic["available"] and logic["node_count"]==6
    assert all(len(s["nodes"])<=4 for s in logic["stages"])
    assert sorted(n["name"] for s in logic["stages"] for n in s["nodes"])==sorted(n["name"] for n in raw["nodes"])
    branch=next(s for s in logic["stages"] if any(n["name"]=="Check" for n in s["nodes"]))
    assert len(branch["nodes"])==1
    assert {e["label"] for e in logic["edges"] if e["source"]==branch["id"]}=={"True","False"}
    merge=next(s for s in logic["stages"] if any(n["name"]=="Merge" for n in s["nodes"]))
    assert len(merge["nodes"])==1
    assert build_logic_map(None)["available"] is False


def test_workflow_logic_cycles_and_four_node_limit():
    from app.modules.workflow_logic import extract_topology, build_logic_map
    names=[f"Step {n}" for n in range(9)]
    raw={"nodes":[{"name":n,"type":"n8n-nodes-base.set"} for n in names],"connections":{n:{"main":[[{"node":names[(i+1)%len(names)]}]]} for i,n in enumerate(names)}}
    logic=build_logic_map(extract_topology(raw))
    assert sorted(len(s["nodes"]) for s in logic["stages"])==[1,4,4]
    assert len(logic["edges"])==3
    assert build_logic_map(extract_topology({"nodes":[{"name":"Same"},{"name":"Same"}]}))["available"] is False


def test_workflow_logic_api_is_workspace_scoped(client, owner):
    params, headers=owner
    integration=connect(client,owner)
    send_failure(client,integration)
    worker.drain_outbox_once()
    workflow=client.get("/workflows",params=params).json()["data"][0]
    assert client.get(f"/workflows/{workflow['id']}",params=params).json()["data"]["logic"]["available"] is False
    from app.modules.workflow_logic import extract_topology
    with db.get_session_factory()() as session:
        stored=session.get(Workflow,uuid.UUID(workflow["id"]))
        stored.provider_metadata={"topology":extract_topology({"nodes":[{"name":"Receive order","type":"n8n-nodes-base.webhook","parameters":{"token":"hidden"}}],"connections":{}})}
        session.commit()
    detail=client.get(f"/workflows/{workflow['id']}",params=params).json()["data"]
    assert detail["logic"]["node_count"]==1
    assert "hidden" not in str(detail)
    assert client.get(f"/workflows/{workflow['id']}",params={"workspace_id":str(uuid.uuid4())}).status_code in (403,404)

def test_monitoring_pause_preserves_history_and_skips_new_runs(client,owner):
    params,headers=owner
    integration=connect(client,owner)
    send_failure(client,integration,execution='before-pause')
    worker.drain_outbox_once()
    workflow=client.get('/workflows',params=params).json()['data'][0]
    assert client.patch(f"/workflows/{workflow['id']}",params=params,headers=headers,json={'monitoring_enabled':False,'environment':'staging'}).status_code==200
    send_failure(client,integration,execution='during-pause')
    worker.drain_outbox_once()
    executions=client.get('/executions',params=params).json()['data']
    assert [e['external_id'] for e in executions]==['before-pause']
    assert client.get('/analytics/overview',params=params).json()['data']['monitored_workflows']==0
    assert client.get(f"/workflows/{workflow['id']}/health",params=params).json()['data']['health_state']=='inactive'
    assert client.patch(f"/workflows/{workflow['id']}",params=params,headers=headers,json={'monitoring_enabled':True}).status_code==200
    send_failure(client,integration,execution='after-resume')
    worker.drain_outbox_once()
    assert len(client.get('/executions',params=params).json()['data'])==2


def test_workspace_timezone_validation(client,owner):
    params,headers=owner
    response=client.patch('/workspaces/'+params['workspace_id'],headers=headers,json={'timezone':'Not/AZone'})
    assert response.status_code==422
    response=client.patch('/workspaces/'+params['workspace_id'],headers=headers,json={'timezone':'Asia/Karachi'})
    assert response.status_code==200
    assert client.get('/auth/me').json()['data']['memberships'][0]['timezone']=='Asia/Karachi'


def test_retention_is_bounded_and_keeps_incident_evidence(client,owner):
    from app.modules.retention import run_retention_once
    params,headers=owner
    integration=connect(client,owner)
    event=send_failure(client,integration,execution='retained-evidence').json()['data']
    worker.drain_outbox_once()
    old=db.utcnow()-timedelta(days=120)
    with db.get_session_factory()() as session:
        event_row=session.get(InboundEvent,uuid.UUID(event['event_id']))
        event_row.received_at=old
        workflow=session.execute(select(Workflow).where(Workflow.workspace_id==uuid.UUID(params['workspace_id']))).scalar_one()
        linked=session.execute(select(Execution).where(Execution.workflow_id==workflow.id)).scalar_one()
        linked.first_observed_at=old
        for n in range(3):session.add(Execution(workspace_id=workflow.workspace_id,workflow_id=workflow.id,external_id='old-'+str(n),status='success',first_observed_at=old))
        pending=InboundEvent(workspace_id=workflow.workspace_id,integration_id=uuid.UUID(integration['id']),source_event_key=uuid.uuid4().hex,event_type='execution.failed',received_at=old,payload_redacted={'keep':'pending'},processing_status='pending')
        session.add(pending);session.commit();pending_id=pending.id;linked_id=linked.id
    counts=run_retention_once(batch_size=1)
    assert counts['payloads_cleared']==1 and counts['executions_removed']==1
    with db.get_session_factory()() as session:
        assert session.get(InboundEvent,uuid.UUID(event['event_id'])).payload_redacted is None
        assert session.get(InboundEvent,pending_id).payload_redacted=={'keep':'pending'}
        assert session.get(Execution,linked_id) is not None
        assert session.scalar(select(func.count(Execution.id)).where(Execution.workflow_id==workflow.id))==3


def test_n8n_result_data_keeps_only_failed_node_name():
    adapter=N8nAdapter()
    normalized=adapter.normalize_execution_payload({'id':'17','workflowId':'wf','status':'error','data':{'resultData':{'error':{'name':'NodeApiError','message':'Timed out','httpCode':'504','node':{'name':'Charge payment','parameters':{'private':'never-copy'},'credentials':{'id':'secret'}}}}}})
    assert normalized.failed_node=='Charge payment'
    assert normalized.error_code=='504' and normalized.error_message_redacted=='Timed out'
    assert 'never-copy' not in str(normalized) and 'secret' not in str(normalized)
    workflow,event=adapter.parse_error_webhook_payload({'workflow':{'id':'wf'},'trigger':{'error':{'name':'TriggerError','message':'Activation failed','node':{'name':'Schedule','parameters':{'private':'never-copy'}}}}})
    assert event['event_type']=='trigger.failed' and event['last_node_executed']=='Schedule'
    assert event['error']['message']=='Activation failed'


def test_n8n_api_requests_include_error_data_and_workflow_filter(monkeypatch):
    adapter=N8nAdapter();calls=[]
    def request(method,url,credential,params=None,**kwargs):
        calls.append((url,params));return {'data':[]} if url.endswith('/executions') else {'id':'17','status':'success'}
    monkeypatch.setattr(adapter,'_request',request)
    adapter.list_executions('https://n8n.example.com','test',None,10,'wf')
    adapter.get_execution('https://n8n.example.com','test','17')
    assert calls[0][1]=={'limit':10,'includeData':'true','workflowId':'wf'}
    assert calls[1][1]=={'includeData':'true'}


def test_sse_tail_pages_through_equal_timestamps(database,monkeypatch):
    from app.modules import stream
    from app.models.models import OutboxMessage
    stamp=db.utcnow()+timedelta(days=1)
    with db.get_session_factory()() as session:
        session.add_all([OutboxMessage(aggregate_type='sse_event',aggregate_id=uuid.uuid4(),message_type='sse.event',payload={'event':'test'},created_at=stamp,available_at=stamp,published_at=stamp) for _ in range(1001)])
        session.commit()
    monkeypatch.setattr(stream.tail_state,'last_ts',stamp)
    monkeypatch.setattr(stream.tail_state,'last_id',uuid.UUID(int=0))
    ids=[]
    for expected in [500,500,1,0]:
        rows=stream._poll_tail_rows();assert len(rows)==expected
        ids.extend(r.id for r in rows)
        if rows:stream.tail_state.last_ts=rows[-1].created_at;stream.tail_state.last_id=rows[-1].id
    assert len(set(ids))==1001


def test_migration_schema_matches_models(database):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from app.core.migrations import current_revision
    from app.models.models import Base
    assert current_revision()=='0002_monitoring'
    with db.get_engine().connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection,opts={'compare_type':True}),Base.metadata)==[]


def test_status_and_resolution_rules_are_delivered_events(client,owner):
    from app.modules.status_alerts import evaluate_status_alerts_once
    params,headers=owner;integration=connect(client,owner)
    channel=client.post('/notification-channels',params=params,headers=headers,json={'name':'Status log','channel_type':'log','configuration':{}}).json()['data']['id']
    response=client.post('/alert-rules',params=params,headers=headers,json={'name':'Status events','event_types':['workflow.inactive','incident.escalated','incident.resolved'],'channel_ids':[channel],'cooldown_seconds':300})
    assert response.status_code==201,response.text
    send_failure(client,integration);worker.drain_outbox_once()
    workflow=client.get('/workflows',params=params).json()['data'][0]
    with db.get_session_factory()() as session:
        stored=session.get(Workflow,uuid.UUID(workflow['id']));stored.is_active=False;session.commit()
    assert evaluate_status_alerts_once()>=1
    count=len(client.get('/notifications',params=params).json()['data'])
    evaluate_status_alerts_once()
    assert len(client.get('/notifications',params=params).json()['data'])==count
    incident=client.get('/incidents',params=params).json()['data'][0]
    assert client.patch('/incidents/'+incident['id'],params=params,headers=headers,json={'severity':'critical'}).status_code==200
    assert client.post('/incidents/'+incident['id']+'/resolve',params=params,headers=headers,json={'resolution_note':'Verified'}).status_code==200
    notifications=client.get('/notifications',params=params).json()['data']
    assert len(notifications)==count+2


def test_sync_failure_degrades_connection_and_queues_alert(client,owner,monkeypatch):
    from app.adapters.base import AdapterError
    from app.core.security import encrypt_secret
    params,headers=owner;integration=connect(client,owner)
    channel=client.post('/notification-channels',params=params,headers=headers,json={'name':'Connection log','channel_type':'log','configuration':{}}).json()['data']['id']
    assert client.post('/alert-rules',params=params,headers=headers,json={'name':'Connection events','event_types':['integration.disconnected'],'channel_ids':[channel]}).status_code==201
    with db.get_session_factory()() as session:
        stored=session.get(Integration,uuid.UUID(integration['id']));stored.base_url='https://example.com';stored.status='healthy';stored.credential_ciphertext=encrypt_secret('test-key')[0]
        cursor=SyncCursor(integration_id=stored.id,resource_type='workflows',next_poll_at=db.utcnow());session.add(cursor);session.commit();cursor_id=cursor.id
    def fail(*args,**kwargs):raise AdapterError('integration_auth_failed','Source rejected credentials',401)
    from app.adapters.n8n.adapter import get_adapter
    monkeypatch.setattr(get_adapter('n8n'),'list_workflows',fail)
    assert worker._run_sync_cursor(db.get_session_factory(),cursor_id)==0
    stored=client.get('/integrations/'+integration['id'],params=params).json()['data']
    assert stored['status']=='degraded' and stored['last_error_code']=='integration_auth_failed'
    assert len(client.get('/notifications',params=params).json()['data'])==1


def test_incident_history_paginates_and_preserves_long_comments(client,owner):
    params,headers=owner;integration=connect(client,owner)
    send_failure(client,integration);worker.drain_outbox_once()
    incident=client.get('/incidents',params=params).json()['data'][0]
    body='Investigation detail. '*180
    for comment in [body,'Follow-up one','Follow-up two']:
        assert client.post('/incidents/'+incident['id']+'/comments',params=params,headers=headers,json={'body':comment}).status_code==201
    seen=[];cursor=None
    for _ in range(10):
        response=client.get('/incidents/'+incident['id']+'/timeline',params={**params,'limit':2,**({'cursor':cursor} if cursor else {})})
        assert response.status_code==200,response.text
        page=response.json();seen.extend(page['data']);cursor=page['meta']['next_cursor']
        if not cursor:break
    assert len({row['id'] for row in seen})==len(seen)
    assert any(row['message']==body for row in seen)
    assert len(seen)>=4
