"""Add a sanitized sample map only to the isolated development preview."""
import json, sys, uuid
from pathlib import Path
from sqlalchemy import select
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.core import config,db
from app.models.models import Workflow,Workspace
from app.modules.workflow_logic import extract_topology
assert config.settings.app_env=='development'
record=json.loads((Path(__file__).resolve().parents[2]/'.local/preview-credentials.json').read_text())
with db.get_session_factory()() as session:
 workspace=session.get(Workspace,uuid.UUID(record['workspace_id']))
 assert workspace.name=='Local preview · Sample data'
 workflow=session.execute(select(Workflow).where(Workflow.workspace_id==workspace.id,Workflow.external_id=='preview-0')).scalar_one()
 names=['Receive order','Normalize fields','Validate order','Find customer','Prepare payment','Calculate tax','Set currency','Payment API','Create invoice','Update order','Notify team','Write audit record']
 types=['webhook','set','code','postgres','set','code','set','httpRequest','httpRequest','postgres','slack','postgres']
 raw={'nodes':[{'name':n,'type':'n8n-nodes-base.'+t} for n,t in zip(names,types)],'connections':{n:{'main':[[{'node':names[i+1]}]]} for i,n in enumerate(names[:-1])}}
 workflow.provider_metadata={'topology':extract_topology(raw),'fixture':True}
 session.commit()
print('Updated only the synthetic preview workflow map.')
