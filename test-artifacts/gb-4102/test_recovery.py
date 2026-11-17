import sys,time,subprocess,json
sys.path.insert(0,'/tmp')
from apitest import *
t=login()
mysql=['/tmp/trialenv/bin/mysql','--socket=/tmp/mysqlrun/mysql.sock','-uroot','indextrial','-e']
def sql(s):return subprocess.run(mysql+[s],check=True,capture_output=True,text=True).stdout
def create_wl(name,sensor):
 return call('POST','/workloads',{'name':name,'sensor_id':sensor,'start_at':'2026-11-01T00:00:00','end_at':'2026-11-30T23:59:59','device_type':None,'description':'recovery test'},t,200)[1]
def create_cand(wl,cols,name):
 return call('POST','/candidates',{'name':name,'workload_id':wl['id'],'columns':cols,'note':''},t,200)[1]
def completed_exp(cand,name):
 _,e=call('POST','/experiments',{'name':name,'candidate_id':cand['id']},t,200)
 e=wait_exp(e['id'],t);assert e['status']=='completed',e
 return e

# ---- Case 1: index built but not registered, adopt on retry (no duplicate create) ----
wl=create_wl('恢复测试负载 R','sensor_id' and 23)
c=create_cand(wl,['sensor_id','recorded_at'],'恢复候选 R1')
e=completed_exp(c,'recover-exp-1')
_,pl=call('POST','/index-plans',{'experiment_id':e['id'],'index_name':'idx_live_wl_rec1'},t,200)
# stop worker so queue item waits
subprocess.run(['pkill','-f','src.worker']);time.sleep(.5)
_,op=call('POST',f"/index-plans/{pl['id']}/publish",None,t,200)
# simulate crash after CREATE INDEX but before registration
sql('CREATE INDEX idx_live_wl_rec1 ON telemetry (sensor_id, recorded_at)')
# retry same operation: should adopt existing entity and not fail on duplicate
_,retry=call('POST',f"/index-operations/{op['id']}/retry",None,t,200)
assert retry['id']==op['id'],retry
# execute once manually (worker down) - idempotent adoption path
subprocess.run(['/tmp/trialenv/bin/python','-I','/tmp/exec_op.py',str(op['id'])],check=True)
ops=call('GET','/index-operations',token=t)[1];o=next(x for x in ops if x['id']==op['id'])
assert o['status']=='completed',o
assert o['evidence']['adopted'] is True,o['evidence']
plans=call('GET','/index-plans',token=t)[1];p=plan_by_id(plans,pl['id'])
assert p['status']=='active' and p['verified'],p
names=[i['index_name'] for i in indexes(t)['indexes']]
assert names.count('idx_live_wl_rec1')==1,names
# execute again as duplicate queue item: no duplicate index, no error
subprocess.run(['/tmp/trialenv/bin/python','-I','/tmp/exec_op.py',str(op['id'])],check=True)
ops=call('GET','/index-operations',token=t)[1];o=next(x for x in ops if x['id']==op['id'])
assert o['status']=='completed',o
assert [i['index_name'] for i in indexes(t)['indexes']].count('idx_live_wl_rec1')==1
print('adopt-on-crash & duplicate queue item ok')
subprocess.run(['/tmp/trialenv/bin/redis-cli','-p','16379','flushall'],check=True,capture_output=True)
subprocess.Popen(['/tmp/start_worker.sh'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True);time.sleep(2)

# ---- Case 2: external same-name occupation rejected, field kept ----
wl2=create_wl('外部占用负载 E',41)
c2=create_cand(wl2,['sensor_id','device_type','recorded_at'],'外部候选 E1')
e2=completed_exp(c2,'recover-exp-2')
_,pl2=call('POST','/index-plans',{'experiment_id':e2['id'],'index_name':'idx_live_wl_ext1'},t,200)
sql('CREATE INDEX idx_live_wl_ext1 ON telemetry (recorded_at, sensor_id)')
_,op2=call('POST',f"/index-plans/{pl2['id']}/publish",None,t,200)
subprocess.run(['/tmp/trialenv/bin/python','-I','/tmp/exec_op.py',str(op2['id'])],check=True)
ops=call('GET','/index-operations',token=t)[1];o=next(x for x in ops if x['id']==op2['id'])
assert o['status']=='conflict',o
plans=call('GET','/index-plans',token=t)[1];p=plan_by_id(plans,pl2['id'])
assert p['status']=='conflict' and p['error'],p
ent=indexes(t)['indexes'];ext=next(i for i in ent if i['index_name']=='idx_live_wl_ext1')
assert ext['columns']==['recorded_at','sensor_id'],ext
assert o['evidence']['entity']['columns']==['recorded_at','sensor_id'],o['evidence']
print('external same-name conflict kept field:',o['error'])
# retry after conflict does not overwrite external definition
subprocess.run(['/tmp/trialenv/bin/python','-I','/tmp/exec_op.py',str(op2['id'])],check=True)
ext=next(i for i in indexes(t)['indexes'] if i['index_name']=='idx_live_wl_ext1')
assert ext['columns']==['recorded_at','sensor_id'],ext
print('conflict retry still leaves field intact')

# ---- Case 3: concurrent publish vs rollback do not overwrite ----
wl3=create_wl('并发测试负载 C',53)
ca=create_cand(wl3,['sensor_id','recorded_at'],'并发候选 A')
cb=create_cand(wl3,['sensor_id','device_type','recorded_at'],'并发候选 B')
cc=create_cand(wl3,['device_type','sensor_id','recorded_at'],'并发候选 C')
ea=completed_exp(ca,'race-exp-a');eb=completed_exp(cb,'race-exp-b');ec=completed_exp(cc,'race-exp-c')
_,pa=call('POST','/index-plans',{'experiment_id':ea['id'],'index_name':'idx_live_wl_raceA'},t,200)
_,pb=call('POST','/index-plans',{'experiment_id':eb['id'],'index_name':'idx_live_wl_raceB'},t,200)
_,pc=call('POST','/index-plans',{'experiment_id':ec['id'],'index_name':'idx_live_wl_raceC'},t,200)
_,opA=call('POST',f"/index-plans/{pa['id']}/publish",None,t,200)
subprocess.run(['/tmp/trialenv/bin/python','-I','/tmp/exec_op.py',str(opA['id'])],check=True)
_,opB=call('POST',f"/index-plans/{pb['id']}/publish",None,t,200)
subprocess.run(['/tmp/trialenv/bin/python','-I','/tmp/exec_op.py',str(opB['id'])],check=True)
# now B active with previous A. fire publish C and rollback B concurrently -> exactly one wins
import threading
res={}
def fire(key,path):
 try:res[key]=call('POST',path,None,t,200)[1]
 except AssertionError as e:res[key]=str(e)
def runop(key):
 subprocess.run(['/tmp/trialenv/bin/python','-I','/tmp/exec_op.py',str(res[key]['id'])],check=True)
fire('pubC',f"/index-plans/{pc['id']}/publish")
fire('rbB',f"/index-plans/{pb['id']}/rollback")
assert isinstance(res['pubC'],dict) and isinstance(res['rbB'],dict),(res['pubC'],res['rbB'])
th=[threading.Thread(target=runop,args=('pubC',)),threading.Thread(target=runop,args=('rbB',))]
[x.start() for x in th];[x.join() for x in th]
ops=call('GET','/index-operations',token=t)[1]
oC=next(x for x in ops if x['id']==res['pubC']['id']);oR=next(x for x in ops if x['id']==res['rbB']['id'])
print('race pubC',oC['status'],oC.get('error'));print('race rbB',oR['status'],oR.get('error'))
assert [oC['status'],oR['status']].count('completed')==1,(oC['status'],oR['status'])
plans=call('GET','/index-plans',token=t)[1]
active=[p for p in plans if p['status']=='active' and p['workload_id']==wl3['id']]
assert len(active)==1,active
names=[i['index_name'] for i in indexes(t)['indexes']]
if oC['status']=='completed':
 assert active[0]['id']==pc['id'] and 'idx_live_wl_racec' in [n.lower() for n in names] and 'idx_live_wl_raceb' not in [n.lower() for n in names],(active,names)
else:
 assert active[0]['id']==pa['id'] and 'idx_live_wl_racea' in [n.lower() for n in names] and 'idx_live_wl_raceb' not in [n.lower() for n in names],(active,names)
print('concurrent publish/rollback no overwrite ok')


# ---- Case 4: concurrent publish of two plans - one completes, other conflicts; no duplicate active ----
wl4=create_wl('并发发布负载 P',67)
c1=create_cand(wl4,['sensor_id','recorded_at'],'并发发布候选 1')
c2=create_cand(wl4,['sensor_id','device_type','recorded_at'],'并发发布候选 2')
e1=completed_exp(c1,'race-pub-1');e2=completed_exp(c2,'race-pub-2')
_,q1=call('POST','/index-plans',{'experiment_id':e1['id'],'index_name':'idx_live_wl_par1'},t,200)
_,q2=call('POST','/index-plans',{'experiment_id':e2['id'],'index_name':'idx_live_wl_par2'},t,200)
res={}
def fire2(key,path):
 res[key]=call('POST',path,None,t,200)[1]
fire2('q1',f"/index-plans/{q1['id']}/publish");fire2('q2',f"/index-plans/{q2['id']}/publish")
th=[threading.Thread(target=lambda k: subprocess.run(['/tmp/trialenv/bin/python','-I','/tmp/exec_op.py',str(res[k]['id'])],check=True),args=(k,)) for k in ('q1','q2')]
[x.start() for x in th];[x.join() for x in th]
ops=call('GET','/index-operations',token=t)[1]
oa=next(x for x in ops if x['id']==res['q1']['id']);ob=next(x for x in ops if x['id']==res['q2']['id'])
print('parallel publish1',oa['status'],oa.get('error'));print('parallel publish2',ob['status'],ob.get('error'))
assert sorted([oa['status'],ob['status']])==['completed','conflict'],(oa['status'],ob['status'])
plans=call('GET','/index-plans',token=t)[1]
active=[p for p in plans if p['status']=='active' and p['workload_id']==wl4['id']]
assert len(active)==1,active
names=[i['index_name'] for i in indexes(t)['indexes']]
assert [n.lower() for n in names].count(active[0]['index_name'].lower())==1,names
loser='idx_live_wl_par1' if oa['status']=='conflict' else 'idx_live_wl_par2'
assert loser not in [n.lower() for n in names],names
print('concurrent publish isolated; loser index not created:',names)
print('ALL RECOVERY/RACE TESTS PASSED')
