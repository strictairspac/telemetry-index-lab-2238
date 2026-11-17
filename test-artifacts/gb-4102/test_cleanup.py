import sys,time,subprocess
sys.path.insert(0,'/tmp')
from apitest import *
t=login()
mysql=['/tmp/trialenv/bin/mysql','--socket=/tmp/mysqlrun/mysql.sock','-uroot','indextrial','-e']
def sql(s):return subprocess.run(mysql+[s],check=True,capture_output=True,text=True).stdout
def idx():return {i['index_name'].lower():i['columns'] for i in indexes(t)['indexes']}
subprocess.Popen(['/tmp/start_worker.sh'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True);time.sleep(2)
subprocess.run(['pkill','-f','python -m src.worker']);time.sleep(.5)
# prepare a completed publish and an external + resident index, then stale trial indexes
_,w=call('POST','/workloads',{'name':'清理边界负载 S','sensor_id':88,'start_at':'2026-11-01T00:00:00','end_at':'2026-11-30T23:59:59','device_type':None,'description':'cleanup'},t,200)
_,c=call('POST','/candidates',{'name':'清理候选 S1','workload_id':w['id'],'columns':['sensor_id','recorded_at'],'note':''},t,200)
_,e=call('POST','/experiments',{'name':'cleanup-exp-1','candidate_id':c['id']},t,200)
subprocess.run(['/tmp/trialenv/bin/python','-I','/tmp/exec_exp.py',str(e['id'])],check=True)
_,e2=call('GET',f"/experiments/{e['id']}",token=t,expect=200)
# create resident via publish path (worker down, run operation manually)
_,p=call('POST','/index-plans',{'experiment_id':e['id'],'index_name':'idx_live_wl_keep'},t,200)
_,op=call('POST',f"/index-plans/{p['id']}/publish",None,t,200)
subprocess.run(['/tmp/trialenv/bin/python','-I','/tmp/exec_op.py',str(op['id'])],check=True)
sql('CREATE INDEX ext_keep_me ON telemetry (value)')
sql('CREATE INDEX trial_ev_stale1 ON telemetry (device_type)')
# stale index belonging to a queued experiment must be kept for resume
_,eq=call('POST','/experiments',{'name':'cleanup-exp-queued','candidate_id':c['id']},t,200)
subprocess.run(['/tmp/trialenv/bin/mysql','--socket=/tmp/mysqlrun/mysql.sock','-uroot','indextrial','-e',"UPDATE experiments SET status='running' WHERE id=%d"%eq['id']],check=True)
sql('CREATE INDEX trial_ev_%d ON telemetry (sensor_id, recorded_at)'%eq['id'])
before=idx()
assert 'idx_live_wl_keep' in before and 'ext_keep_me' in before and 'trial_ev_stale1' in before
subprocess.Popen(['/tmp/start_worker.sh'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
eq2=wait_exp(eq['id'],t,timeout=120);assert eq2['status']=='completed',eq2
time.sleep(.5)
after=idx()
print('before',sorted(before));print('after',sorted(after))
assert 'idx_live_wl_keep' in after,'resident removed'
assert 'ext_keep_me' in after,'external removed'
assert 'trial_ev_stale1' not in after,'stale trial not cleaned'
assert 'trial_ev_%d'%eq['id'] not in after,'queued experiment index should be consumed by resumed trial, not left behind'
print('cleanup boundaries ok')
print('ALL CLEANUP TESTS PASSED')
