from src.services import index_publishing as svc
from src.services.audit import log
def create_plan(data,user):
 row=svc.create_plan(data,user.email);log(user.email,'index.plan.create',str(data.experiment_id));return row
def publish(plan_id,user):
 row=svc.request_publish(plan_id,user.email);log(user.email,'index.publish.queue',str(plan_id));return row
def rollback(plan_id,user):
 row=svc.request_rollback(plan_id,user.email);log(user.email,'index.rollback.queue',str(plan_id));return row
def retry(operation_id,user):
 row=svc.retry_operation(operation_id,user.email);log(user.email,'index.operation.retry',str(operation_id));return row
