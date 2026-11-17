"""Controlled MySQL index trial. All dynamic identifiers are server-whitelisted.

每次试验使用独占临时索引名 trial_ev_<experiment>。试验前后的基线不删除任何常驻
或外部索引，只记录它们作为基线；清理阶段仅删除本次试验自己的临时索引。
候选发布后仍保留常驻索引并参与后续试验基线。
"""
import hashlib,json,time,statistics
from sqlalchemy import text
from src.config.database import engine
from src.constants.enums import COLUMNS,INDEX_LOCK,TRIAL_PREFIX
from src.services.index_publishing import telemetry_indexes,index_entity,_classify
def prefix_score(columns,w):
 equality={'sensor_id'}|({'device_type'} if w.get('device_type') else set())
 score=0;matched=[];reason=[]
 for col in columns:
  if col in equality:score+=40;matched.append(col);reason.append(f'{col}: equality prefix +40')
  elif col=='recorded_at':score+=20;matched.append(col);reason.append('recorded_at: range +20; following columns cannot extend lookup');break
  else:reason.append(f'{col}: unmatched prefix stops lookup');break
 return {'score':min(100,score),'matched_prefix':matched,'reason':reason,'formula':'equality prefix +40/column, first range +20, max 100; heuristic only'}
def _timed(conn,query,params):
 samples=[];rows=[]
 for _ in range(5):
  start=time.perf_counter();rows=[dict(r) for r in conn.execute(text(query),params).mappings()];samples.append((time.perf_counter()-start)*1000)
 return rows,round(statistics.median(samples),4),[round(x,4) for x in samples]
def _write_probe(conn):
 t=time.perf_counter()
 conn.execute(text("INSERT INTO telemetry(sensor_id,recorded_at,device_type,value) VALUES (999,'2026-11-17T12:00:00','pump',42.5)"),[{} for _ in range(20)])
 elapsed=(time.perf_counter()-t)*1000;conn.rollback();return round(elapsed,4)
def trial_index_name(run_id):
 return f'{TRIAL_PREFIX}{run_id}'
def _parse_snapshot_columns(snapshot):
 columns=snapshot['candidate']['columns']
 if not columns or any(c not in COLUMNS for c in columns) or len(set(columns))!=len(columns):raise ValueError('invalid index columns')
 return columns
def run(snapshot,run_id=None):
 w=snapshot['workload'];columns=_parse_snapshot_columns(snapshot)
 if run_id is None:run_id=snapshot.get('experiment_id') or 'adhoc'
 name=trial_index_name(run_id)
 params={'sensor':w['sensor_id'],'start':w['start_at'],'end':w['end_at']}
 query='SELECT id,sensor_id,recorded_at,device_type,value FROM telemetry WHERE sensor_id=:sensor AND recorded_at>=:start AND recorded_at<=:end'
 if w.get('device_type'):query+=' AND device_type=:device';params['device']=w['device_type']
 query+=' ORDER BY id'
 with engine.connect() as conn:
  if conn.execute(text('SELECT GET_LOCK(:l,30)'),{'l':INDEX_LOCK}).scalar()!=1:raise RuntimeError('another trial or publish holds lock')
  adopted=False
  try:
   existing=index_entity(conn,name)
   if existing['exists'] and existing['columns']!=list(columns):
    raise RuntimeError(f'trial index {name} exists with a different definition; kept in place for manual review')
   before_indexes=[x for x in telemetry_indexes(conn) if x['index_name']!=name]
   resident=[dict(x,role=_classify(x['index_name'])) for x in before_indexes if _classify(x['index_name']) in ('resident','external')]
   before=[dict(r) for r in conn.execute(text('EXPLAIN '+query),params).mappings()]
   rows,before_ms,before_samples=_timed(conn,query,params)
   write_before=_write_probe(conn)
   if existing['exists']:
    adopted=True
   else:
    conn.execute(text('CREATE INDEX `'+name+'` ON telemetry ('+','.join('`'+c+'`' for c in columns)+')'));conn.commit()
   conn.execute(text('ANALYZE TABLE telemetry')).all()
   after=[dict(r) for r in conn.execute(text('EXPLAIN '+query),params).mappings()]
   result,after_ms,after_samples=_timed(conn,query,params)
   write_after=_write_probe(conn)
   canonical=lambda records:hashlib.sha256(json.dumps(records,sort_keys=True).encode()).hexdigest()
   return {'prefix':prefix_score(columns,w),'query':query,'parameters':params,'rows':len(result),'before_plan':before,'after_plan':after,'before_median_ms':before_ms,'after_median_ms':after_ms,'before_samples_ms':before_samples,'after_samples_ms':after_samples,'insert20_before_ms':write_before,'insert20_after_ms':write_after,'equal_results':canonical(rows)==canonical(result),'checksum':canonical(result),'preview':result[:10],'trial_index':name,'trial_index_adopted':adopted,'resident_indexes':resident,'baseline':{'kept_indexes':[x['index_name'] for x in before_indexes],'resident_indexes':[x['index_name'] for x in resident if x['role']=='resident'],'external_indexes':[x['index_name'] for x in resident if x['role']=='external'],'note':'基线保留常驻与外建索引，仅候选索引为本次新增变量'},'limitations':['5000-row deterministic dataset; timings include Python driver and cache effects','20-row write probe is rolled back; sequence gaps are normal','heuristic prefix score is not MySQL optimizer cost; no guaranteed speedup','trial index is temporary; only resident published indexes persist']}
  finally:
   conn.rollback()
   try:
    current=index_entity(conn,name)
    if current['exists']:
     if current['columns']==list(columns):conn.execute(text('DROP INDEX `'+name+'` ON telemetry'));conn.commit()
   finally:conn.execute(text('SELECT RELEASE_LOCK(:l)'),{'l':INDEX_LOCK});conn.commit()
