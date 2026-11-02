from alembic import context
from app.core.db import get_engine
from app.models.models import Base

def include_object(obj,name,type_,reflected,compare_to):
    return not (type_=='table' and name=='alembic_version')

if context.is_offline_mode():
    from app.core.config import settings
    context.configure(url=settings.database_url,target_metadata=Base.metadata,literal_binds=True,dialect_opts={'paramstyle':'named'},include_object=include_object)
    with context.begin_transaction():
        context.run_migrations()
else:
    with get_engine().connect() as connection:
        context.configure(connection=connection,target_metadata=Base.metadata,compare_type=True,include_object=include_object)
        with context.begin_transaction():
            context.run_migrations()
