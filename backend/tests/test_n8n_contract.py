"""Opt-in, read-only public API contract against an operator's test n8n.

Supply N8N_TEST_BASE_URL and N8N_TEST_API_KEY. The instance must contain at
least two workflows and saved successful/failed runs. This never creates or
executes workflows. Credentials are never printed.
"""
import os
import pytest
from app.core import config
from app.adapters.n8n.adapter import N8nAdapter


@pytest.mark.skipif(not (os.environ.get('N8N_TEST_BASE_URL') and os.environ.get('N8N_TEST_API_KEY')),
                    reason='Opt-in live n8n test instance not configured')
def test_live_n8n_public_read_contract(monkeypatch):
    monkeypatch.setattr(config.settings,'allow_private_network',os.environ.get('N8N_TEST_ALLOW_PRIVATE_NETWORK')=='true')
    base=os.environ['N8N_TEST_BASE_URL'];key=os.environ['N8N_TEST_API_KEY'];adapter=N8nAdapter()
    assert adapter.test_connection(base,key)['ok']
    first=adapter.list_workflows(base,key,None,1)
    assert len(first.items)==1 and first.next_cursor, 'Test instance requires at least two workflows'
    second=adapter.list_workflows(base,key,first.next_cursor,1)
    assert second.items and second.items[0].external_id!=first.items[0].external_id
    assert first.items[0].provider_metadata.get('topology') is not None
    executions=adapter.list_executions(base,key,None,100)
    assert {'success','failed'}<={e.status for e in executions.items}, 'Test instance needs saved success and failure runs'
    failed=next(e for e in executions.items if e.status=='failed')
    detail=adapter.get_execution(base,key,failed.external_id)
    assert detail and detail.status=='failed' and detail.failed_node and detail.error_message_redacted
    assert not adapter.capabilities.retry_execution
