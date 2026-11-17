import sys,time,subprocess
sys.path.insert(0,'/tmp')
from apitest import *
t=login()
mysql=['/tmp/trialenv/bin/mysql','--socket=/tmp/mysqlrun/mysql.sock','-uroot','indextrial','-e']
def sql(s):return subprocess.run(mysql+[s],check=True,capture_output=True,text=True).stdout
def wl(name,sensor):return call('POST','/workloads',{'name':name,'sensor_id':sensor,'start_at':'2026-11-01T00:00:00','end_at':'2026-11-30T23:59:59','device_type':None,'description':'restart'},t,200)[1]
def cand(w,cols,name):return call('POST','/candidates',{'name':name,'workload_id':w['id'],'columns':cols,'note':''},t,200)[1]
def exp(c,name):
 _,e=call('POST','/experiments',{'name':name,'candidate_id':c['id']},t,200);e=wait_exp(e['id'],t);assert e['status']=='completed',e;return e
subprocess.Popen(['/tmp/start_worker.sh'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True);time.sleep(2)
# interruption: index created but not registered; worker down; operation pending
w=wl('重启恢复负载 W',71);c=cand(w,['sensor_id','recorded_at'],'重启恢复候选 W1');e=exp(c,'restart-exp-1')
subprocess.run(['pkill','-f','src.worker']);time.sleep(.5)
_,p=call('POST','/index-plans',{'experiment_id':e['id'],'index_name':'idx_live_wl_restart'},t,200)
_,op=call('POST',f"/index-plans/{p['id']}/publish",None,t,200)
sql('CREATE INDEX idx_live_wl_restart ON telemetry (sensor_id, recorded_at)')
# simulate experiment interrupted at running
_,e2=call('POST','/experiments',{'name':'restart-exp-2','candidate_id':c['id']},t,200)
subprocess.run(['/tmp/trialenv/bin/mysql','--socket=/tmp/mysqlrun/mysql.sock','-uroot','indextrial','-e',"UPDATE experiments SET status='running' WHERE id=%d"%e2['id']],check=True)
subprocess.Popen(['/tmp/start_worker.sh'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True);time.sleep(3)
op=wait_op(op['id'],t,timeout=60)
print('recovered op',op['id'],op['status'],op['evidence'] and op['evidence'].get('adopted'))
assert op['status']=='completed' and op['evidence']['adopted'] is True,op
e2=wait_exp(e2['id'],t,timeout=120)
print('recovered experiment',e2['status'])
assert e2['status']=='completed',e2
names=[i['index_name'].lower() for i in indexes(t)['indexes']]
assert names.count('idx_live_wl_restart')==1,names
assert not any(n.startswith('trial_ev_') for n in names),names
print('interruption recovery ok',names)
print('ALL RESTART TESTS PASSED')
