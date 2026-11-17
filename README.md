# 岩川 · 设备遥测索引试验室

为岩川设备可靠性组 12 人把检索负载、索引候选与真实 MySQL 试验串成可复查工作流。

## 业务场景
上游来自泵站温升告警与值班 SQL 文件。过去同事在表格记录列顺序、手动建索引后截取计划，存在参数版本混乱、前后结果不一致未发现、写入代价未记录三项痛点。本站生成固定 SELECT，在专用 5,000 行遥测库内串行建索引、采集执行计划、保存输入快照，交给可靠性复核人判断。

模块：工作负载录入/编辑、候选列序设计、后台试验队列、真实结果对比/JSON 导出、索引发布与回退；管理员另有审计。核心实体 workloads / candidates / experiments / index_plans / index_operations，样本表 telemetry。

## 快速启动
```sh
cp .env.example .env
docker compose up -d --build
docker compose exec -T backend python -m scripts.seed_demo
```
前端 http://localhost:18241 ，后端 OpenAPI http://localhost:19241/docs ，MySQL localhost:17741（trial / trialpass / indextrial）。结束 `docker compose down -v --remove-orphans` 会清除本地数据。

| 角色 | 账号 | 权限 | 典型动作 |
|---|---|---|---|
| admin | admin@index.local | 全部、审计 | 复查谁执行了哪次试验 |
| operator | operator@index.local | 新建/编辑/执行/导出 | 保存候选并执行 |
| viewer | viewer@index.local | 读取/导出 | 复核证据，写请求返回403 |

统一密码 `Trial2026!`，仅为本地演示。JWT 8 小时，密码 PBKDF2。公开部署前须替换凭据、JWT 密钥及网络访问策略。

## 一天剧本
1. 09:00 operator 登录，查看「泵站17温升排查」。
2. 09:05 查看 sensor_id=17、2026-11-01 至 2026-11-30 的输入范围。
3. 09:10 新建 `shift-20261117` 工作负载，描述 `泵站17夜班复核.csv`。
4. 09:15 保存 `传感器17时间窗` 候选列 `sensor_id,recorded_at`。
5. 09:20 创建 `shift-20261117` 试验，worker 真正建索引和执行查询。
6. 09:25 查看 EXPLAIN、前缀评分、结果 SHA-256、写入探针。
7. 09:30 导出 `trial-<id>.json`，viewer 登录只读复核。
8. 09:35 在「索引发布」用该试验创建方案，发布为常驻索引 `idx_live_wl_17_pN`；页面核对实体后显示生效。
9. 10:00 admin 查看审计记录并检查执行完成事件。

## 索引发布与回退
- 只能用**已完成且结果等价**的试验建方案。方案列定义在创建时从试验快照复制，候选之后修改不影响已建方案。
- 发布在 worker 中真实创建常驻索引；先查 `information_schema.statistics` 核对列序与非唯一性，核对通过才登记生效，否则报告冲突且不动现场。
- 回退把当前生效方案标为已回退，恢复 `previous_plan_id` 指向的前一生效方案；若应恢复的索引已存在且定义一致就接回，不重复创建。
- 发布、回退与试验共用一把 MySQL GET_LOCK 串行执行，提交登记前再次确认生效方案未被其它操作改变；不一致则整体拒绝。
- 同一方案重复点击发布/回退复用未完成的同一条操作；操作失败后可「重试同一操作」，按实体核对幂等续跑。
- worker 重启会接回 queued/running 试验与 pending/running 发布/回退；若索引已建成未登记，会核对并接回，不会重复建索引。
- 同名索引若列定义不同，创建方案与执行阶段都会拒绝并保留原索引；外部手工索引与已发布常驻索引在后续试验中只作为基线记录，试验清理只删自己的 `trial_ev_<id>` 临时索引。

种子含三账号、三负载、三候选与 5,000 遥测行。固定公式生成，不依赖随机数。seed 根据自然键/id补缺，不覆盖用户编辑。范围错误/非法列/重复名称有错误响应，空结果仍可正常比较。

## 算法与真实边界
Python 对索引从左到右分析，匹配相等列每列 +40，首个时间范围列 +20 后停止，最高100。缺失首列停止。启发式不等于优化器成本。worker 使用 MySQL GET_LOCK 串行隔离，删除遗留试验临时索引 → 无候选基线 EXPLAIN/查询5次 → 建候选索引/ANALYZE → 查询5次和EXPLAIN → 校验有序全结果SHA-256 → 清理本次临时索引；已发布常驻索引与外部索引保留并记为基线。数据固定、查询参数固定可复现，耗时受缓存和驱动波动影响，不保证提速。20 行写探针是真实 INSERT 后 ROLLBACK，可能消耗 auto_increment 序列号。试验只修改专用 telemetry 表，不能接受任意SQL或远端数据库。任务使用简单 Redis 单消费者，进程崩溃后的 queued/running 任务在 worker 重启后接回；同一试验的临时索引名由 experiment_id 决定，可幂等续跑。

## 技术与目录
Python3.11 / FastAPI / SQLAlchemy / PyMySQL / Redis；MySQL8.0；原生 HTML CSS ES modules；nginx1.27。恰好五容器 frontend/backend/worker/db/redis，均有健康探针。数据库、Redis、应用产物各用命名卷。

`backend/src` 按 models/schemas/services/controllers/routes/middlewares/config/constants/utils 分层；`backend/scripts/seed_demo.py`；`backend/migrations` 记录元数据建表版本。`frontend/src` 按 api/stores/pages/components/common/hooks/router/types/constants/utils 分层。截图、测试脚本及测试报告在批次根目录 `test-artifacts/gb-4102`，不放源码。

共享枚举：角色、试验状态与发布方案/操作状态在 `backend/src/constants/enums.py` 与 `frontend/src/constants/enums.js`；服务/权限与前端状态组件使用一致枚举。前端共享 table/status/feedback 与发布状态 plan 组件；hooks forms/poll。双字体来自 Google Fonts（网络不可用时回退 sans-serif/monospace）。赭红工业试验纸视觉，支持桌面/平板/手机。

环境变量 `.env.example`：COMPOSE_PROJECT_NAME、FRONTEND_PORT、BACKEND_PORT、DB_PORT、JWT_SECRET、SEED_DEMO。容器内 DATABASE_URL/REDIS_URL 来自 Compose。SEED_DEMO启动失败仅记录日志；正常启动一次自然键补缺。全局错误处理/请求追踪中间件、JWT授权与业务审计横切。

本地开发：`pip install -r backend/requirements.txt`，设置 DATABASE_URL、REDIS_URL、JWT_SECRET 后在 backend 运行 `uvicorn src.main:app --reload`；前端需 nginx `/api/` 反向代理或开发代理，直接file://不能运行。许可 MIT。
