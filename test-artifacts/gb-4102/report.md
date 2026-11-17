# gb-4102 索引发布验证报告

环境：本地 MySQL 9.7（兼容 MySQL 8 语法）+ Redis 8 + FastAPI/worker，实际执行 CREATE/DROP INDEX 与 information_schema 核对。
说明：当前执行环境没有 Docker，因此以同版本 Python 依赖 + 本地 MySQL/Redis 启动真实后端与 worker 完成验证；Compose 五容器未改动。

## 覆盖场景与结果

| 场景 | 断言 | 结果 |
|---|---|---|
| 已完成且等价试验创建方案 | 仅 completed + equal_results 可建 | 通过 |
| 候选后续修改不影响发布 | 改候选列后重复建方案，列定义仍来自试验快照 | 通过 |
| 发布改变遥测表索引 | 发布后 information_schema 出现常驻索引且列序一致 | 通过 |
| 实体核对后才成功 | 操作 completed 且 evidence.entity.verified=true | 通过 |
| 发布顶替 + 回退恢复前一生效 | 旧方案 superseded；回退后旧索引恢复、新索引删除 | 通过 |
| 同名异定义拒绝并保留现场 | 建方案 409；执行期 conflict；外部索引列定义未变 | 通过 |
| 同名索引方案级冲突 | 同名不同列方案被 409，现场未改 | 通过 |
| 建成但未登记 → 接回 | 模拟 CREATE 后崩溃，重试同一操作 adopted=true，索引仅 1 个 | 通过 |
| 同次重试不重复建索引 | 重复执行同一 operation 幂等完成 | 通过 |
| worker 重启接回 | pending 操作与 running 试验均恢复；无残留 trial_ev 索引 | 通过 |
| 并发发布/回退 | 两者只有一个 completed，生效方案唯一 | 通过 |
| 并发两个发布 | 一个 completed 一个 conflict；失败方索引未创建 | 通过 |
| 后续试验保留常驻索引 | baseline.resident_indexes 含已发布索引，且试验后仍存在 | 通过 |
| 外部索引不被清理 | baseline.external_indexes 含手工索引，试验后仍存在 | 通过 |
| 启动清理不误删 | 遗留 trial_ev_stale1 被清理；常驻 idx_live_wl_keep、外部 ext_keep_me 保留；排队试验的临时索引留给恢复执行 | 通过 |
| 前端展示 | 生效方案、实体核对、操作沿革、回退/重试按钮渲染 | 通过 |

## 日志与脚本
- `publish.log` / `test_publish.py`：发布、顶替、回退、基线保留、外部索引保留
- `recovery.log` / `test_recovery.py`：接回、幂等、同名冲突、并发发布/回退、并发发布
- `restart.log` / `test_restart.py`：worker 重启恢复
- `cleanup.log` / `test_cleanup.py`：启动清理边界（常驻/外部/排队试验临时索引）
- `frontend.log` / `frontend/test_frontend.mjs`：前端页面渲染断言
- `apitest.py`：测试公共 HTTP 辅助

复现：需要可运行的 MySQL 与 Redis，设置 DATABASE_URL / REDIS_URL / JWT_SECRET 后运行对应脚本；脚本会创建独立负载与候选，不会改动种子数据。

## 已知边界
- 简单 Redis 单消费者；多个 worker 进程时靠 MySQL GET_LOCK 串行化索引变更，但队列仍按单消费者假设设计。
- 索引名称由用户提供时仅允许小写字母/数字/下划线；MySQL 在大小写不敏感文件系统上会把名字落成小写，界面读取实体时按小写匹配。
- 回退只恢复前一生效方案，不实现任意历史版本跳转。
