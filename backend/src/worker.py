import time,logging,redis
from pathlib import Path
from src.config.settings import REDIS_URL
from src.config.database import Session
from src.models.experiment import Experiment
from src.services.index_algorithm import run
from src.services import experiments, index_publishing
from src.services.audit import log
q=redis.Redis.from_url(REDIS_URL)
def recover():
 for _ in range(30):
  Path('/tmp/worker-heartbeat').touch()
  try:
   trials=experiments.recover_pending();operations=index_publishing.recover_pending()
   stale=index_publishing.cleanup_stale_trial_indexes()
   logging.info('recovered pending queues trials=%s operations=%s stale_trial_indexes=%s',trials,operations,stale)
   return
  except Exception:
   logging.exception('queue recovery failed; retrying');time.sleep(2)
def run_trial(run_id):
 with Session() as s:
  row=s.get(Experiment,run_id)
  if not row or row.status=='completed':return
  row.status='running';row.error=None;snapshot=dict(row.snapshot or {});snapshot['experiment_id']=row.id;s.commit()
 try:
  result=run(snapshot,run_id=run_id)
  with Session() as s:
   r=s.get(Experiment,run_id);r.result=result;r.status='completed';r.error=None;s.commit()
  log('worker','experiment.completed',str(run_id))
 except Exception as exc:
  logging.exception('trial failed')
  with Session() as s:r=s.get(Experiment,run_id);r.status='failed';r.error=str(exc)[:1000];s.commit()
def main():
 recover()
 while True:
  Path('/tmp/worker-heartbeat').touch()
  try:
   item=q.blpop(['index-operations','index-trials'],timeout=2)
   if not item:continue
   queue_name,raw=item
   item_id=int(raw)
   if queue_name==b'index-operations':index_publishing.execute_operation(item_id)
   else:run_trial(item_id)
  except Exception:logging.exception('worker loop');time.sleep(2)
if __name__=='__main__':main()
