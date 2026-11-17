from fastapi import APIRouter,Depends
from src.middlewares.auth import current,writer
from src.schemas.business import PlanInput
from src.services import index_publishing
from src.controllers.index_publishing import create_plan,publish,rollback,retry
router=APIRouter()
@router.get('/index-plans')
def plans(u=Depends(current)):return index_publishing.list_plans()
@router.get('/index-operations')
def operations(u=Depends(current)):return index_publishing.list_operations()
@router.get('/telemetry/indexes')
def indexes(u=Depends(current)):return index_publishing.entity_state()
@router.post('/index-plans')
def create(data:PlanInput,u=Depends(writer)):return create_plan(data,u)
@router.post('/index-plans/{plan_id}/publish')
def publish_plan(plan_id:int,u=Depends(writer)):return publish(plan_id,u)
@router.post('/index-plans/{plan_id}/rollback')
def rollback_plan(plan_id:int,u=Depends(writer)):return rollback(plan_id,u)
@router.post('/index-operations/{operation_id}/retry')
def retry_operation(operation_id:int,u=Depends(writer)):return retry(operation_id,u)
