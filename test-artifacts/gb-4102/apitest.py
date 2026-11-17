import json,time,urllib.request,urllib.error,sys
BASE='http://127.0.0.1:18000'
def call(method,path,data=None,token=None,expect=None):
 body=json.dumps(data).encode() if data is not None else None
 req=urllib.request.Request(BASE+path,data=body,method=method,headers={'Content-Type':'application/json',**({'Authorization':'Bearer '+token} if token else {})})
 try:
  with urllib.request.urlopen(req) as r:code=r.status;out=json.loads(r.read() or b'null')
 except urllib.error.HTTPError as e:
  code=e.code;out=json.loads(e.read() or b'null')
 if expect and code!=expect:raise AssertionError(f'{method} {path} -> {code} {out}, expected {expect}')
 return code,out
def login(email='operator@index.local'):
 return call('POST','/auth/login',{'email':email,'password':'Trial2026!'},expect=200)[1]['token']
def wait(pred,timeout=40,label='condition'):
 end=time.time()+timeout
 while time.time()<end:
  value=pred()
  if value:return value
  time.sleep(.4)
 raise AssertionError('timeout: '+label)
def wait_op(op_id,token,timeout=60):
 return wait(lambda:(lambda o:(o if o['status'] in ('completed','conflict','failed') else None))(call('GET','/index-operations',token=token)[1][0] if False else next((o for o in call('GET','/index-operations',token=token)[1] if o['id']==op_id),None)),timeout,'operation '+str(op_id))
def wait_exp(exp_id,token,timeout=90):
 return wait(lambda:(lambda e:(e if e['status'] in ('completed','failed') else None))(call('GET',f'/experiments/{exp_id}',token=token)[1]),timeout,'experiment')
def plan_by_id(plans,pid):return next(p for p in plans if p['id']==pid)
def indexes(token):return call('GET','/telemetry/indexes',token=token,expect=200)[1]
