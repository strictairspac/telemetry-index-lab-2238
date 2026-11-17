import sys,time,json
sys.path.insert(0,'/tmp')
from apitest import *
t=login()
# create a workload and two candidates for isolation
_,w=call('POST','/workloads',{'name':'发布测试负载 A','sensor_id':17,'start_at':'2026-11-01T00:00:00','end_at':'2026-11-30T23:59:59','device_type':None,'description':'publish test'},t,200)
_,c1=call('POST','/candidates',{'name':'发布候选 17A','workload_id':w['id'],'columns':['sensor_id','recorded_at'],'note':''},t,200)
_,c2=call('POST','/candidates',{'name':'发布候选 17B','workload_id':w['id'],'columns':['sensor_id','device_type','recorded_at'],'note':''},t,200)
def run(cand,name):
 _,e=call('POST','/experiments',{'name':name,'candidate_id':cand['id']},t,200)
 e=wait_exp(e['id'],t)
 assert e['status']=='completed',e
 assert e['result']['equal_results'] is True,e['result']
 return e
e1=run(c1,'publish-exp-1')
print('experiment1 resident baseline',e1['result']['baseline'])
# plan from completed experiment
_,p1=call('POST','/index-plans',{'experiment_id':e1['id'],'index_name':'idx_live_wl_pub1'},t,200)
print('plan1',p1['id'],p1['index_name'],p1['status'])
# candidate mutation must not affect plan
_,c1b=call('PUT',f"/candidates/{c1['id']}",{'name':c1['name'],'workload_id':w['id'],'columns':['sensor_id','device_type'],'note':'changed'},t,200)
_,p1_again=call('POST','/index-plans',{'experiment_id':e1['id'],'index_name':'idx_live_wl_pub1'},t,200)
assert p1_again['id']==p1['id'] and p1_again['columns']==['sensor_id','recorded_at'],p1_again
print('candidate change isolated: ok')
# publish
_,op=call('POST',f"/index-plans/{p1['id']}/publish",None,t,200)
op=wait_op(op['id'],t)
print('publish op',op['id'],op['status'],op.get('error'))
assert op['status']=='completed',op
plans=call('GET','/index-plans',token=t)[1]
active=[p for p in plans if p['status']=='active' and p['workload_id']==w['id']]
assert len(active)==1 and active[0]['id']==p1['id'],plans
ent=active[0]['entity'];assert ent['exists'] and ent['matches'],ent
idx=indexes(t);assert any(i['index_name']=='idx_live_wl_pub1' for i in idx['indexes']),idx
print('publish verified entity ok',ent)
# second plan overlapping same index name with different columns -> reject, field intact
e2=run(c2,'publish-exp-2')
code,out=call('POST','/index-plans',{'experiment_id':e2['id'],'index_name':'idx_live_wl_pub1'},t)
print('same name different def',code,out if code!=200 else out['columns'])
assert code==409,out
idx2=indexes(t);assert any(i['index_name']=='idx_live_wl_pub1' for i in idx2['indexes']),idx2
# publish plan2 with unique name; previous index removed, baseline retained
_,p2=call('POST','/index-plans',{'experiment_id':e2['id'],'index_name':'idx_live_wl_pub2'},t,200)
_,op2=call('POST',f"/index-plans/{p2['id']}/publish",None,t,200)
op2=wait_op(op2['id'],t);assert op2['status']=='completed',op2
plans=call('GET','/index-plans',token=t)[1]
assert plan_by_id(plans,p1['id'])['status']=='superseded',plans
assert plan_by_id(plans,p2['id'])['status']=='active'
idx=indexes(t);names=[i['index_name'] for i in idx['indexes']]
assert 'idx_live_wl_pub2' in names and 'idx_live_wl_pub1' not in names,names
print('publish supersede ok',names)
# rollback restores previous
_,op3=call('POST',f"/index-plans/{p2['id']}/rollback",None,t,200)
op3=wait_op(op3['id'],t);assert op3['status']=='completed',op3
plans=call('GET','/index-plans',token=t)[1]
assert plan_by_id(plans,p2['id'])['status']=='rolled_back'
assert plan_by_id(plans,p1['id'])['status']=='active'
idx=indexes(t);names=[i['index_name'] for i in idx['indexes']]
assert 'idx_live_wl_pub1' in names and 'idx_live_wl_pub2' not in names,names
print('rollback restores previous ok',names)
# subsequent experiment keeps resident index as baseline
e3=run(c2,'publish-exp-3')
print('exp3 baseline',e3['result']['baseline'])
assert 'idx_live_wl_pub1' in e3['result']['baseline']['resident_indexes'],e3['result']['baseline']
idx=indexes(t);assert any(i['index_name']=='idx_live_wl_pub1' for i in idx['indexes']),idx
print('subsequent trial preserves resident index: ok')
# external index survives trial cleanup
import subprocess
subprocess.run(['/tmp/trialenv/bin/mysql','--socket=/tmp/mysqlrun/mysql.sock','-uroot','indextrial','-e','CREATE INDEX ext_manual_17 ON telemetry (sensor_id, value)'],check=True)
e4=run(c1,'publish-exp-4')
assert 'ext_manual_17' in e4['result']['baseline']['external_indexes'],e4['result']['baseline']
idx=indexes(t);assert any(i['index_name']=='ext_manual_17' for i in idx['indexes']),idx
print('external index preserved on trial: ok')
print('ALL PUBLISH TESTS PASSED')
