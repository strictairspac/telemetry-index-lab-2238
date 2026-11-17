"""索引发布与回退。

方案在请求时从已完成且结果等价的试验快照复制列定义，候选之后修改不影响发布。
发布/回退与试验共用同一把 MySQL 咨询锁串行化；所有成功的操作都必须先在
information_schema 中核对真实索引实体，核对通过才登记为生效。
"""
import hashlib,json,re
from datetime import datetime
from fastapi import HTTPException
from sqlalchemy import text
from src.config.database import Session,engine
from src.constants.enums import COLUMNS,INDEX_LOCK,RESIDENT_PREFIX,REQUEST_LOCK,TRIAL_PREFIX
from src.models.experiment import Experiment
from src.models.index_plan import IndexPlan,IndexOperation
from src.models.workload import Workload
from src.services.audit import log
from src.utils.serialization import record

NAME_PATTERN=re.compile(r'^[a-z][a-z0-9_]{2,63}$')

class Conflict(Exception):
 def __init__(self,message,evidence=None):
  super().__init__(message);self.evidence=evidence or {}

def _digest(snapshot):
 return hashlib.sha256(json.dumps(snapshot,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def _valid_columns(columns):
 return bool(columns) and all(c in COLUMNS for c in columns) and len(set(columns))==len(columns)

def index_entity(conn,name):
 """读取一个索引的真实列序与唯一性；不存在时返回 exists=False。"""
 rows=[(r[0],r[1],r[2]) for r in conn.execute(text("SELECT column_name,non_unique,index_type FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='telemetry' AND index_name=:n ORDER BY seq_in_index"),{'n':name})]
 if not rows:return {'exists':False,'index_name':name,'columns':[],'non_unique':None,'index_type':None}
 return {'exists':True,'index_name':name,'columns':[r[0] for r in rows],'non_unique':rows[0][1],'index_type':rows[0][2]}

def telemetry_indexes(conn):
 grouped={}
 for name,column,non_unique,index_type in conn.execute(text("SELECT index_name,column_name,non_unique,index_type FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='telemetry' ORDER BY index_name,seq_in_index")):
  item=grouped.setdefault(name,{'index_name':name,'columns':[],'non_unique':non_unique,'index_type':index_type})
  item['columns'].append(column)
 return sorted(grouped.values(),key=lambda x:x['index_name'])

def _classify(name):
 if name=='PRIMARY':return 'primary'
 if name.startswith(RESIDENT_PREFIX):return 'resident'
 if name.startswith(TRIAL_PREFIX):return 'trial'
 return 'external'

def _verify(conn,name,columns):
 entity=index_entity(conn,name)
 entity['expected_columns']=list(columns)
 entity['columns_match']=entity['exists'] and entity['columns']==list(columns)
 entity['non_unique_ok']=entity['non_unique']==1
 entity['verified']=bool(entity['columns_match'] and entity['non_unique_ok'])
 entity['checked_at']=datetime.now().isoformat(timespec='seconds')
 return entity

def _drop(conn,name):
 conn.execute(text('DROP INDEX `'+name+'` ON telemetry'));conn.commit()

def _create(conn,name,columns):
 conn.execute(text('CREATE INDEX `'+name+'` ON telemetry ('+','.join('`'+c+'`' for c in columns)+')'));conn.commit()

def _active_plans(session,workload_id):
 return session.query(IndexPlan).filter_by(workload_id=workload_id,status='active').order_by(IndexPlan.id.asc()).all()

def _current_active(session,workload_id):
 rows=_active_plans(session,workload_id)
 if len(rows)>1:raise Conflict('同一负载存在多个生效方案，已停止自动操作，请人工核对',{'active_plan_ids':[p.id for p in rows]})
 return rows[0] if rows else None

def _other_active_claims(session,index_name,exclude_plan_id=None):
 """同一遥测表上的一个索引只能被一个生效方案占用，避免跨负载互相删除。"""
 if not index_name:return []
 rows=session.query(IndexPlan).filter(IndexPlan.status=='active',IndexPlan.index_name==index_name).all()
 return [p for p in rows if p.id!=exclude_plan_id]

def _plan_record(p):
 d=record(p);d['entity']=None;d['previous_plan_id']=p.previous_plan_id
 return d

def list_plans():
 with Session() as s:
  plans=[_plan_record(p) for p in s.query(IndexPlan).order_by(IndexPlan.id.desc()).limit(200).all()]
 with engine.connect() as conn:
  live={x['index_name'].lower():x for x in telemetry_indexes(conn)}
 for p in plans:
  if p.get('index_name'):
   entity=live.get(p['index_name'].lower(),{'index_name':p['index_name'],'columns':[],'non_unique':None,'index_type':None})
   p['entity']={'exists':'columns' in entity and bool(entity['columns']),'columns':entity.get('columns',[]),'matches':entity.get('columns',[])==p['columns'],'classified':_classify(p['index_name'])}
  if p['status']=='active' and p.get('verification'):
   p['verification_current']=p['entity']['matches']
 return plans

def list_operations(limit=200):
 with Session() as s:return [record(o) for o in s.query(IndexOperation).order_by(IndexOperation.id.desc()).limit(limit).all()]

def entity_state():
 with engine.connect() as conn:
  indexes=telemetry_indexes(conn)
 for x in indexes:x['classified']=_classify(x['index_name'])
 with Session() as s:
  plans={p.index_name.lower():p for p in s.query(IndexPlan).filter(IndexPlan.status=='active').all() if p.index_name}
 return {'indexes':indexes,'active_by_index':{k:{'plan_id':v.id,'columns':v.columns,'verified':v.verified} for k,v in plans.items()},'lock':INDEX_LOCK,'trial_prefix':TRIAL_PREFIX,'resident_prefix':RESIDENT_PREFIX}

def create_plan(data,actor):
 with engine.connect() as conn:
  if conn.execute(text('SELECT GET_LOCK(:l,10)'),{'l':REQUEST_LOCK}).scalar()!=1:raise HTTPException(503,'发布请求繁忙，请稍后重试')
  try:
   with Session() as s:
    exp=s.get(Experiment,data.experiment_id)
    if not exp:raise HTTPException(404,'未找到试验')
    if exp.status!='completed':raise HTTPException(409,'只能用已完成的试验创建发布方案')
    result=exp.result or {}
    if not result.get('equal_results'):
     raise HTTPException(409,'试验尚未证明候选索引与基线结果等价，不能发布')
    columns=list((exp.snapshot or {}).get('candidate',{}).get('columns') or [])
    if not _valid_columns(columns):raise HTTPException(409,'试验快照中的索引列无效')
    if not s.get(Workload,exp.workload_id):raise HTTPException(404,'未找到试验对应负载')
    existing=s.query(IndexPlan).filter(IndexPlan.experiment_id==exp.id,IndexPlan.status.in_(('pending','active'))).order_by(IndexPlan.id.desc()).all()
    wanted=(data.index_name or '').strip().lower()
    reuse=next((p for p in existing if not wanted or p.index_name==wanted),None)
    if reuse:return _plan_record(reuse)
    plan=IndexPlan(experiment_id=exp.id,workload_id=exp.workload_id,columns=columns,status='pending',snapshot_digest=_digest(exp.snapshot or {}))
    s.add(plan);s.flush()
    plan.index_name=(wanted or f'{RESIDENT_PREFIX}_{exp.workload_id}_p{plan.id}').strip().lower()
    if not NAME_PATTERN.match(plan.index_name) or plan.index_name.startswith(TRIAL_PREFIX):
     raise HTTPException(422,'索引名称只能使用小写字母、数字和下划线，且不能使用试验临时前缀')
    same=s.query(IndexPlan).filter(IndexPlan.index_name==plan.index_name,IndexPlan.id!=plan.id).all()
    clash=[p for p in same if list(p.columns)!=columns and p.status not in ('rolled_back','failed')]
    if clash:
     other=clash[0]
     raise HTTPException(409,f'同名索引 {plan.index_name} 已被方案 #{other.id} 用于不同列定义，现场未改动')
    with engine.connect() as c2:
     entity=index_entity(c2,plan.index_name)
    if entity['exists'] and entity['columns']!=columns:
     raise HTTPException(409,f'同名索引 {plan.index_name} 已存在于遥测表但列定义不同，已拒绝且未改动现场')
    s.commit();s.refresh(plan)
    out=_plan_record(plan)
  finally:
   conn.execute(text('SELECT RELEASE_LOCK(:l)'),{'l':REQUEST_LOCK});conn.commit()
 log(actor,'index.plan.create',f'plan={out["id"]} experiment={out["experiment_id"]} index={out["index_name"]} columns={",".join(out["columns"])}')
 return out

def _request_lock():
 return REQUEST_LOCK

def _pending_operation(s,action,plan_id):
 return s.query(IndexOperation).filter_by(action=action,plan_id=plan_id).filter(IndexOperation.status.in_(('pending','running'))).order_by(IndexOperation.id.desc()).first()

def _queue_operation(operation_id):
 from src.services.experiments import queue
 try:queue.rpush('index-operations',operation_id)
 except Exception:
  with Session() as s:
   op=s.get(IndexOperation,operation_id)
   if op:op.status='pending';op.error='队列暂不可用，可稍后重试同一操作';s.commit()
  raise HTTPException(503,'发布队列不可用，请稍后重试同一操作')

def _new_operation(action,plan,actor,expected_plan_id):
 op=IndexOperation(action=action,status='pending',experiment_id=plan.experiment_id,plan_id=plan.id,workload_id=plan.workload_id,index_name=plan.index_name,columns=list(plan.columns),expected_plan_id=expected_plan_id,actor=actor)
 return op

def request_publish(plan_id,actor):
 with engine.connect() as conn:
  if conn.execute(text('SELECT GET_LOCK(:l,10)'),{'l':_request_lock()}).scalar()!=1:raise HTTPException(503,'发布请求繁忙，请稍后重试')
  try:
   with Session() as s:
    plan=s.get(IndexPlan,plan_id)
    if not plan:raise HTTPException(404,'未找到发布方案')
    if plan.status=='active':
     done=s.query(IndexOperation).filter_by(action='publish',plan_id=plan.id,status='completed').order_by(IndexOperation.id.desc()).first()
     if done:return record(done)
     raise HTTPException(409,'方案已标记生效但缺少完成记录，请人工核对实体索引')
    if plan.status in ('superseded','rolled_back'):
     raise HTTPException(409,'方案已失效，请基于对应试验重新创建发布方案')
    pending=_pending_operation(s,'publish',plan.id)
    if pending:
     s.commit();out=record(pending)
    else:
     current=_current_active(s,plan.workload_id)
     op=_new_operation('publish',plan,actor,current.id if current else None)
     plan.previous_plan_id=current.id if current else None
     s.add(op);s.commit();s.refresh(op);out=record(op)
   _queue_operation(out['id'])
  finally:
   conn.execute(text('SELECT RELEASE_LOCK(:l)'),{'l':_request_lock()});conn.commit()
 log(actor,'index.publish.queued',f'plan={plan_id} operation={out["id"]}')
 return out

def request_rollback(plan_id,actor):
 with engine.connect() as conn:
  if conn.execute(text('SELECT GET_LOCK(:l,10)'),{'l':_request_lock()}).scalar()!=1:raise HTTPException(503,'发布请求繁忙，请稍后重试')
  try:
   with Session() as s:
    plan=s.get(IndexPlan,plan_id)
    if not plan:raise HTTPException(404,'未找到发布方案')
    if plan.status=='rolled_back':
     done=s.query(IndexOperation).filter_by(action='rollback',plan_id=plan.id,status='completed').order_by(IndexOperation.id.desc()).first()
     if done:return record(done)
     raise HTTPException(409,'方案已回退但缺少完成记录，请人工核对实体索引')
    if plan.status!='active':raise HTTPException(409,'只有当前生效的方案才能回退')
    if not plan.previous_plan_id:raise HTTPException(409,'该方案没有可恢复的前一生效方案')
    pending=_pending_operation(s,'rollback',plan.id)
    if pending:
     s.commit();out=record(pending)
    else:
     op=_new_operation('rollback',plan,actor,plan.id)
     previous=s.get(IndexPlan,plan.previous_plan_id)
     op.index_name=previous.index_name if previous else None
     op.columns=list(previous.columns) if previous else None
     s.add(op);s.commit();s.refresh(op);out=record(op)
   _queue_operation(out['id'])
  finally:
   conn.execute(text('SELECT RELEASE_LOCK(:l)'),{'l':_request_lock()});conn.commit()
 log(actor,'index.rollback.queued',f'plan={plan_id} operation={out["id"]}')
 return out

def retry_operation(operation_id,actor):
 with Session() as s:
  op=s.get(IndexOperation,operation_id)
  if not op:raise HTTPException(404,'未找到操作')
  if op.status=='completed':
   out=record(op)
  elif op.status=='running':
   raise HTTPException(409,'操作仍在执行中；如 worker 已中断，请等待恢复调度或重启 worker')
  elif op.status=='conflict':
   raise HTTPException(409,'本次操作因现场冲突未生效；请先人工处理冲突（或另建方案）再发布，不应直接重试')
  else:
   op.status='pending';op.error=None;op.finished_at=None;s.commit();s.refresh(op);out=record(op)
   if op.action=='publish' and op.plan_id:
    plan=s.get(IndexPlan,op.plan_id)
    if plan and plan.status=='failed':plan.status='pending';s.commit()
 _queue_operation(out['id'])
 log(actor,'index.operation.retry',f'operation={out["id"]} action={out["action"]}')
 return out

def recover_pending():
 """worker 启动时接回未完成操作；重复入队安全，执行端按实体核对幂等。"""
 with Session() as s:
  ids=[o.id for o in s.query(IndexOperation).filter(IndexOperation.status.in_(('pending','running'))).order_by(IndexOperation.id.asc()).all()]
 if ids:
  from src.services.experiments import queue
  try:
   for i in ids:queue.rpush('index-operations',i)
  except Exception:pass
 return ids

def cleanup_stale_trial_indexes():
 """只清理不属于排队/执行中试验的遗留临时索引；常驻、外部与主键一律不碰。"""
 removed=[]
 with Session() as s:
  pending={f'{TRIAL_PREFIX}{r.id}'.lower() for r in s.query(Experiment).filter(Experiment.status.in_(('queued','running'))).all()}
 with engine.connect() as conn:
  if conn.execute(text('SELECT GET_LOCK(:l,10)'),{'l':INDEX_LOCK}).scalar()!=1:return removed
  try:
   for item in telemetry_indexes(conn):
    name=item['index_name']
    if _classify(name)=='trial' and name.lower() not in pending:
     _drop(conn,name);removed.append(name)
  finally:
   conn.execute(text('SELECT RELEASE_LOCK(:l)'),{'l':INDEX_LOCK});conn.commit()
 if removed:log('worker','index.trial.cleanup',','.join(removed))
 return removed

def _mark_running(op_id):
 with Session() as s:
  op=s.get(IndexOperation,op_id)
  if not op or op.status not in ('pending','running'):return False
  op.status='running'
  if not op.started_at:op.started_at=datetime.now()
  s.commit()
  return True

def _fail(op_id,message,plan_status=None,evidence=None):
 with Session() as s:
  op=s.get(IndexOperation,op_id)
  if not op:return
  op.status='conflict' if isinstance(message,Conflict) else 'failed'
  op.error=str(message)[:1000]
  if evidence:op.evidence=evidence
  op.finished_at=datetime.now()
  if plan_status and op.plan_id:
   plan=s.get(IndexPlan,op.plan_id)
   if plan and plan.status not in ('active','rolled_back','superseded'):
    plan.status=plan_status;plan.error=str(message)[:1000]
    if plan_status=='conflict':plan.verification=evidence.get('entity') if evidence else plan.verification
  s.commit()

def _finished(op_id,evidence):
 with Session() as s:
  op=s.get(IndexOperation,op_id)
  op.status='completed';op.error=None;op.evidence=evidence;op.finished_at=datetime.now();s.commit()

def _prepare_target(conn,name,columns,op_id):
 """确保目标索引真实存在且定义正确。已存在同定义则接回，不再重复建；同名异定义拒绝并保留现场。"""
 entity=index_entity(conn,name)
 if entity['exists']:
  if entity['columns']!=list(columns):
   raise Conflict(f'同名索引 {name} 已存在但列定义不同，已拒绝且未改动现场',{'entity':_verify(conn,name,columns),'adopted':False})
  if entity['non_unique']!=1:
   raise Conflict(f'同名索引 {name} 不是普通非唯一索引，已拒绝且未改动现场',{'entity':_verify(conn,name,columns),'adopted':False})
  verified=_verify(conn,name,columns)
  verified['adopted']=True
  return verified
 _create(conn,name,columns)
 verified=_verify(conn,name,columns)
 if not verified['verified']:
  raise Conflict(f'索引 {name} 建成后实体核对不一致，已保留现场',{'entity':verified,'adopted':False})
 verified['adopted']=False
 return verified

def _ensure_dropped(conn,name,expect_columns):
 if not name:raise Conflict('待清理索引缺少登记名称，已停止操作并保留现场',{'index_name':name})
 entity=index_entity(conn,name)
 if not entity['exists']:return {'index_name':name,'exists':False,'dropped':False}
 if list(expect_columns) and entity['columns']!=list(expect_columns):
  raise Conflict(f'待替换索引 {name} 的真实定义与登记不符，已停止操作并保留现场',{'entity':entity})
 _drop(conn,name)
 after=index_entity(conn,name)
 if after['exists']:raise Conflict(f'清理索引 {name} 后实体仍存在，未报告成功',{'entity':after})
 return {'index_name':name,'exists':False,'dropped':True}

def _publish(conn,op_id,plan):
 with Session() as s:
  plan=s.get(IndexPlan,plan.id)
  op=s.get(IndexOperation,op_id)
  current=_current_active(s,plan.workload_id)
  if plan.status=='active':
   verified=_verify(conn,plan.index_name,plan.columns)
   if verified['verified']:
    _finished(op_id,{'mode':'idempotent','entity':verified,'plan_id':plan.id})
    return
   raise Conflict('方案已登记生效但实体索引核对失败，请人工复核',{'entity':verified})
  if plan.status in ('superseded','rolled_back'):
   raise Conflict('方案状态已失效，不能发布',{'plan_status':plan.status})
  expected=op.expected_plan_id
  current_id=current.id if current else None
  if expected!=current_id:
   raise Conflict('生效方案已被其他发布或回退改变，本次发布未覆盖现场，请重新创建方案',{'expected_plan_id':expected,'actual_active_plan_id':current_id})
  if current and not current.index_name:
   raise Conflict('当前生效方案缺少索引名称，请人工核对',{'plan_id':current.id})
  if current and current.index_name==plan.index_name:
   raise Conflict(f'索引名称 {plan.index_name} 已被当前生效方案占用，请换名后重新创建方案',{'plan_id':current.id})
  claims=_other_active_claims(s,plan.index_name,plan.id)
  if claims:
   raise Conflict(f'索引名称 {plan.index_name} 已被其他生效方案 #{claims[0].id} 占用，未改动现场',{'plan_id':claims[0].id})
  target_verified=_prepare_target(conn,plan.index_name,plan.columns,op_id)
  previous_cleanup=None
  if current:
   previous_cleanup=_ensure_dropped(conn,current.index_name,current.columns)
  evidence={'mode':'published','entity':target_verified,'previous_plan_id':current.id if current else None,'previous_cleanup':previous_cleanup,'adopted':target_verified.get('adopted',False)}
 with Session() as s:
  plan=s.get(IndexPlan,plan.id)
  active=_active_plans(s,plan.workload_id)
  if len(active)>1:
   raise Conflict('提交登记前发现多个生效方案，未覆盖现场',{'active_plan_ids':[p.id for p in active]})
  active_id=active[0].id if active else None
  if active_id!=expected:
   raise Conflict('提交登记前发现生效方案已变化，未覆盖现场',{'expected_plan_id':expected,'actual_active_plan_id':active_id})
  if active:active[0].status='superseded'
  plan.previous_plan_id=expected
  plan.status='active';plan.verified=True;plan.verification=target_verified;plan.error=None;plan.activated_at=datetime.now()
  s.commit()
 _finished(op_id,evidence)

def _rollback(conn,op_id,plan):
 with Session() as s:
  op=s.get(IndexOperation,op_id);plan=s.get(IndexPlan,plan.id);previous=s.get(IndexPlan,plan.previous_plan_id) if plan.previous_plan_id else None
  current=_current_active(s,plan.workload_id)
  if plan.status=='rolled_back':
   if previous and previous.status=='active' and previous.index_name:
    verified=_verify(conn,previous.index_name,previous.columns)
    if verified['verified']:
     _finished(op_id,{'mode':'idempotent','restored_plan_id':previous.id,'entity':verified})
     return
   raise Conflict('方案已回退但前一生效方案核对失败，请人工复核',{'plan_id':plan.id,'previous_plan_id':plan.previous_plan_id})
  if plan.status!='active':raise Conflict('只有当前生效的方案才能回退',{'plan_status':plan.status})
  if not previous:raise Conflict('没有可恢复的前一生效方案',{'plan_id':plan.id})
  if not previous.index_name or not _valid_columns(previous.columns):raise Conflict('前一方案的索引登记不完整，不能回退',{'previous_plan_id':previous.id})
  if op.expected_plan_id!=plan.id or not current or current.id!=plan.id:
   raise Conflict('生效方案已被其他发布或回退改变，本次回退未覆盖现场',{'expected_plan_id':op.expected_plan_id,'actual_active_plan_id':current.id if current else None})
  if current.index_name==previous.index_name:
   raise Conflict(f'当前与前一方案使用同一索引名 {previous.index_name}，无法安全回退',{'plan_id':plan.id})
  claims=_other_active_claims(s,previous.index_name,previous.id)
  if claims:
   raise Conflict(f'待恢复索引名称 {previous.index_name} 已被方案 #{claims[0].id} 生效占用，未改动现场',{'plan_id':claims[0].id})
  target_verified=_prepare_target(conn,previous.index_name,previous.columns,op_id)
  current_cleanup=_ensure_dropped(conn,current.index_name,current.columns)
  evidence={'mode':'rolled_back','entity':target_verified,'restored_plan_id':previous.id,'rolled_back_plan_id':plan.id,'current_cleanup':current_cleanup,'adopted':target_verified.get('adopted',False)}
 with Session() as s:
  plan=s.get(IndexPlan,plan.id);previous=s.get(IndexPlan,previous.id)
  active=_active_plans(s,plan.workload_id)
  if len(active)!=1 or active[0].id!=plan.id:
   raise Conflict('提交回退登记前发现生效方案已变化，未覆盖现场',{'actual_active_plan_ids':[p.id for p in active]})
  if previous.status=='active' and previous.id!=plan.id:
   raise Conflict('前一方案已是生效状态，未覆盖现场',{'previous_plan_id':previous.id})
  plan.status='rolled_back';plan.error=None
  previous.status='active';previous.verified=True;previous.verification=target_verified;previous.error=None;previous.activated_at=datetime.now()
  s.commit()
 _finished(op_id,evidence)

def execute_operation(operation_id):
 if not _mark_running(operation_id):return
 with Session() as s:
  probe=s.get(IndexOperation,operation_id)
  if not probe:
   _fail(operation_id,'操作不存在');return
  action=probe.action;plan_id=probe.plan_id
 with engine.connect() as conn:
  if conn.execute(text('SELECT GET_LOCK(:l,30)'),{'l':INDEX_LOCK}).scalar()!=1:
   _fail(operation_id,'等待试验/发布串行锁超时，未改动任何索引');return
  try:
   with Session() as s:
    op=s.get(IndexOperation,operation_id);plan=s.get(IndexPlan,plan_id)
   if not plan:raise Conflict('发布方案不存在',{'plan_id':plan_id})
   if action=='publish':_publish(conn,operation_id,plan)
   elif action=='rollback':_rollback(conn,operation_id,plan)
   else:raise Conflict(f'未知操作 {action}',{})
  except Conflict as exc:
   _fail(operation_id,exc,'conflict',exc.evidence)
   log('worker',f'index.{action}.conflict',f'operation={operation_id} {exc}')
  except Exception as exc:
   _fail(operation_id,exc)
   log('worker',f'index.{action}.failed',f'operation={operation_id} {exc}')
  finally:
   conn.rollback()
   try:conn.execute(text('SELECT RELEASE_LOCK(:l)'),{'l':INDEX_LOCK});conn.commit()
   except Exception:pass
 with Session() as s:
  op=s.get(IndexOperation,operation_id)
  if op and op.status=='completed':
   plan=s.get(IndexPlan,op.plan_id) if op.plan_id else None
   log(op.actor or 'worker',f'index.{op.action}.completed',f'operation={op.id} plan={op.plan_id} index={plan.index_name if plan else op.index_name}')
