from sqlalchemy import Column,Integer,String,JSON,DateTime,Boolean,ForeignKey,func
from src.config.database import Base
class IndexPlan(Base):
 """一次索引发布方案。列定义在发布请求时从已完成试验快照复制；候选之后修改不影响本方案。"""
 __tablename__='index_plans'
 id=Column(Integer,primary_key=True)
 index_name=Column(String(64),nullable=True)
 experiment_id=Column(Integer,ForeignKey('experiments.id'),nullable=False)
 workload_id=Column(Integer,ForeignKey('workloads.id'),nullable=False)
 columns=Column(JSON,nullable=False)
 snapshot_digest=Column(String(64),nullable=False,default='')
 status=Column(String(20),default='pending',nullable=False)
 previous_plan_id=Column(Integer,nullable=True)
 verified=Column(Boolean,default=False,nullable=False)
 verification=Column(JSON,nullable=True)
 error=Column(String(1000),nullable=True)
 created_at=Column(DateTime,server_default=func.now())
 activated_at=Column(DateTime,nullable=True)
class IndexOperation(Base):
 """发布/回退操作沿革。同一操作重试复用本行，不重复建索引。"""
 __tablename__='index_operations'
 id=Column(Integer,primary_key=True)
 action=Column(String(20),nullable=False)
 status=Column(String(20),default='pending',nullable=False)
 experiment_id=Column(Integer,ForeignKey('experiments.id'),nullable=True)
 plan_id=Column(Integer,ForeignKey('index_plans.id'),nullable=True)
 workload_id=Column(Integer,ForeignKey('workloads.id'),nullable=True)
 index_name=Column(String(64),nullable=True)
 columns=Column(JSON,nullable=True)
 expected_plan_id=Column(Integer,nullable=True)
 actor=Column(String(120),nullable=False,default='')
 evidence=Column(JSON,nullable=True)
 error=Column(String(1000),nullable=True)
 created_at=Column(DateTime,server_default=func.now())
 started_at=Column(DateTime,nullable=True)
 finished_at=Column(DateTime,nullable=True)
