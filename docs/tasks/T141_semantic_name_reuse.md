# T141：FULL Mapping 复用既有有序遍历的完整语义名称

- 状态：`ACCEPTED`
- 负责人：主 Agent（合同、冻结测试与独立验收）/ Luna xhigh 子 Agent（实现、自测）
- 起始分支 / HEAD：`main@457259a`
- 前置：T140 ACCEPTED，已提交并推送 origin/main
- 计划：`docs/development/full_performance_plan.md` 第二步（最后一个实现任务）
- 验收类型：rewrite/mapping；actual-gate 正负 Formal

## 1. 单一目标与输入输出

RenameIndex 已有完整有序 catalog_root 遍历；在其现有分类循环中收集 Mapping 所需的非空字符串
name，消除正常 Mapping build 的一次重复全树 visit。只传递不可变字符串集合，不保存第二份全树。
必读 AGENTS.md、docs/tasks/README.md、docs/development/process/refactor_subagent_protocol.md、
docs/formal_verification.md 和上述计划。

主 Agent 冻结 `tests/test_t141_semantic_name_reuse.py`，不得修改：

- 三种 compile 分支：RenameIndex catalog visit 仍为 1；Mapping 额外 visit 和 `_semantic_names`
  调用均由 1 降为 0。每个 factory 入参仍是精确完整的独立 frozenset 快照。
- T108 确定性命名 `zz` + 顺序递增零填充到 20 字符；完整 mapping.to_report SHA256 必须为
  `e4bea7aee2502f833053859bf9b34a21adf81a17530aaf5faa18f9ae3b2831da`；42 records，34/6/2。
- 未选择类别、非候选语义名称和此前生成的新名仍冲突；不同构建不共享集合。
- dataclasses.replace(index) 不继承 live-only 复用事实（建议 init=False）；替换 catalog/root
  后必须重新收集，不能命中旧名称。既有 Mapping index/owner/manifest/range 验证仍先于名称步骤。
- 名称 getter 的异常不可忽略。可将本次快照标为不可复用，留到原 Mapping 名称步骤重新读取并
  报错；不能在 RenameIndex 阶段提前抛出，或吞掉异常后发布缺名称快照。
- 输出 T141_REUSE_JSON 与 T141_MAPPING_DIGEST；report/schema 无新增缓存字段。

## 2. 最小实现与明确禁区

允许 RenameIndex 增加 init=False、repr=False、compare=False 的私有 live-only 事实，绑定本次
catalog 及 compilation/root/source-manager 身份；Mapping 只在身份匹配时复用。不存在/失效的
快照继续调用原 `_semantic_names`，保持外部构造/replace envelope 的原检查行为；这不是新的
语义 lookup fallback，不得替代 PySlang 解析。空名称集合与无快照必须区分。

名称规则与原 `_semantic_names` 相同：`isinstance(name, str) and name`；不要筛到 selected categories
或 eligible records。沿用已完成 workset 的原节点顺序与所有 projection，不增加 root.visit。
如果 getter 读取失败，放弃整个可复用快照，而不是仅跳过该 node。

不改 factory 接口、不复用一个可变 set 作为入参、不删除逐记录 snapshot/碰撞检查，不修改
SourceCatalog、SourceSet、no-top ABI、四组类别、owner/binding、name-completeness、dead-source、
macro、readonly、rate、gate/restore/Formal 算法。不建全局/磁盘缓存、daemon、新依赖或通用缓存框架。
不运行 RISC/blanket discovery，不删除历史测试。

子 Agent 允许修改：

```text
rtl_obfuscator/rename_index.py
rtl_obfuscator/mapping_vnext.py
docs/development/project_structure.md
docs/tasks/T141_semantic_name_reuse.md
```

project_structure 只补充本次内部复用/失效规则。Main拥有冻结测试、合同和整体计划，不得覆盖。
需要扩范围、改变错误优先级或真实性无法验证时记录并停止，不自行进入第三个实现步骤。

## 3. Baseline（唯一命令）

先记录 HEAD/status 并 READY→IN_PROGRESS：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t141_semantic_name_reuse -v
```

旧实现只应在三分支 Mapping 额外 visit 断言失败，其他 oracle 应通过；不得改 oracle。

## 4. 冻结验收（五条）

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t141_semantic_name_reuse -v

conda run -n rtl_obfuscation python -m unittest tests.test_mapping_vnext tests.test_t128_rename_index_range_cache tests.test_t129_ordered_semantic_workset tests.test_t140_catalog_metadata_index tests.test_t139_filelist_delivery -v

conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rename_index.py rtl_obfuscator/mapping_vnext.py tests/test_t141_semantic_name_reuse.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c 'from pathlib import Path; s=next(l for l in Path("docs/tasks/T141_semantic_name_reuse.md").read_text().splitlines() if l.startswith("- 状态：")); assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t141_ready_for_review=pass")'
```

命令 2 的 T139 actual gate / relocated export Formal 必须 exit 0 / pass JSON；actual gate XOR→OR
negative 非零且含 unproven / equiv_status -assert。记录实际 gold/gate/top、seq、精确脚本命令、JSON；
同时验证非 identity 改名、完整交付、逐字节恢复。所有内部 Python/EDA 使用指定 Conda 环境。

## 5. 子 Agent 执行记录

status: `READY_FOR_REVIEW`
starting_head: `main@457259abf70f46591fec5b4e99f202537eef1dc5`
starting_status: `## main...origin/main`; pre-existing frozen inputs: `docs/tasks/T141_semantic_name_reuse.md`, `tests/test_t141_semantic_name_reuse.py`
start_record: READY→IN_PROGRESS; first command `conda run -n rtl_obfuscation python -m unittest tests.test_t141_semantic_name_reuse -v`
changed_files: `rtl_obfuscator/rename_index.py`, `rtl_obfuscator/mapping_vnext.py`, `docs/development/project_structure.md`, `docs/tasks/T141_semantic_name_reuse.md`
commands:
- baseline `conda run -n rtl_obfuscation python -m unittest tests.test_t141_semantic_name_reuse -v`
- `conda run -n rtl_obfuscation python -m unittest tests.test_t141_semantic_name_reuse -v`
- `conda run -n rtl_obfuscation python -m unittest tests.test_mapping_vnext tests.test_t128_rename_index_range_cache tests.test_t129_ordered_semantic_workset tests.test_t140_catalog_metadata_index tests.test_t139_filelist_delivery -v`
- `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rename_index.py rtl_obfuscator/mapping_vnext.py tests/test_t141_semantic_name_reuse.py`
- `git diff --check HEAD`
- T141 `READY_FOR_REVIEW` state guard (after this record)
results:
- Baseline exit `1` as expected: 8 tests ran; the reuse test failed in three branch subcases, each observing one extra Mapping root visit; all other safety, digest, collision and error-order checks passed.
- T141 target exit `0`, `9` tests passed; `T141_REUSE_JSON` reports `extra_mapping_visits=0` for no-top, top and scoped branches; `T141_MAPPING_DIGEST=e4bea7aee2502f833053859bf9b34a21adf81a17530aaf5faa18f9ae3b2831da`.
- Frozen matrix exit `0`, `37` tests passed; T108 digest `0180e2d80e623f5677e3dbce6cf0259e9a486380d8b4ad7142c023350f23bf9f`, T115 digest `dbbc8fb76135251abcd8f87dca6e78ce3a5df7c19101e1c3907f020d8dd49a78`; T140 membership/index evidence unchanged; T139 complete delivery and byte-restore checks passed.
- `py_compile` exit `0`; `git diff --check HEAD` exit `0`.
schema_or_behavior: one ordered RenameIndex workset pass now records a `frozenset[str]` semantic-name snapshot and a live-only complete identity tuple; Mapping reuses it only for the same catalog, compilation, root and source manager, after existing validation.
boundaries: getter exceptions invalidate the snapshot and defer the original getter failure to Mapping; empty snapshots remain distinct from absent/invalid snapshots; `dataclasses.replace` and incomplete identity tuples fall back to `_semantic_names`; no public report/schema, mutable set, cross-build cache or fallback parser added.
cleanup_candidates: none identified
formal_verification: `PASS`
gold: `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-dmffab0s/project` via `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-dmffab0s/gate/original_design.f`
gate: `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-dmffab0s/gate/design.f`; relocated export `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-dmffab0s/relocated/export_design.f`
top: `t139_top`; seq: `5`
command: `conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-dmffab0s/gate/original_design.f --gold-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-dmffab0s/project --top t139_top --seq 5 --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-dmffab0s/gate/design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-dmffab0s/gate`
relocated_command: `OUT=/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-dmffab0s/relocated conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-dmffab0s/gate/original_design.f --gold-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-dmffab0s/project --top t139_top --seq 5 --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-dmffab0s/relocated/export_design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-dmffab0s/relocated`
negative_command: `OUT=/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-dmffab0s/negative conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-dmffab0s/gate/original_design.f --gold-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-dmffab0s/project --top t139_top --seq 5 --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-dmffab0s/negative/export_design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-dmffab0s/negative`
exit_code: positive `0`, relocated positive `0`, negative `1`
result: positive and relocated JSON `{"formal_equivalence":"pass","top":"t139_top","seq":5}`; negative includes `unproven` and `equiv_status -assert`; actual gate is non-identity renamed and T139 delivery/restore evidence passed.
review_request: implementation and evidence complete; Main Agent must independently rerun the five frozen commands and decide `ACCEPTED`. No commit or push performed.

## 6. 偏差或阻塞

主 Agent 在初读实现时补充冻结 identity 故障注入用例：0/1/3/5 项身份 tuple 都不能通过四项
完整身份校验；避免 zip 截断及 all(empty) 空真。属于既定完整身份边界的负例，不改变功能范围。

## 7. 主 Agent 验收与最终测量

2026-09-15 主 Agent 在正式 READY_FOR_REVIEW 交付后独立重跑第 4 节五条命令：

- 状态 guard exit 0：`t141_ready_for_review=pass`。
- 目标测试 exit 0：9 tests / 0.429s，三分支额外 Mapping visit=0；完整确定性 Mapping digest
  为 `e4bea7aee2502f833053859bf9b34a21adf81a17530aaf5faa18f9ae3b2831da`。
- 冻结矩阵 exit 0：37 tests / 2.128s；T108/T115 决策摘要与 T140 结构计数保持不变。
- py_compile、git diff --check HEAD：exit 0。
- 完整四项身份、getter 失败、replace、旧/新名称碰撞、未选择名称、range-first 错误顺序均通过。
  Main 修正了子 Agent 记录中 T108 digest 末尾漏写一个 f 的抄录错误，未更改 oracle 或实现。

formal_verification: `PASS`。Main 的矩阵独立调用同 Conda 环境中的脚本：

```sh
conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-i3d88_ip/gate/original_design.f --gold-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-i3d88_ip/project --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-i3d88_ip/gate/design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-i3d88_ip/gate --top t139_top --seq 5

OUT=/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-i3d88_ip/relocated conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-i3d88_ip/gate/original_design.f --gold-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-i3d88_ip/project --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-i3d88_ip/relocated/export_design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-i3d88_ip/relocated --top t139_top --seq 5

OUT=/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-i3d88_ip/negative conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-i3d88_ip/gate/original_design.f --gold-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-i3d88_ip/project --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-i3d88_ip/negative/export_design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-i3d88_ip/negative --top t139_top --seq 5
```

两个正例 exit 0，JSON `formal_equivalence=pass, top=t139_top, seq=5`，gold 为上述 project、gate
分别为 gate / relocated；实际 gate XOR→OR 负例 exit 1，含 unproven 与 equiv_status -assert。
非 identity 改名、完整物理交付、逐字节 restore 均由同一矩阵断言。临时目录由测试自动清理。

最终测量详见 `docs/development/full_performance_plan.md`：Main 串行交替运行旧提交与当前实现，
每版本/规模 10 个 warm 样本。256 实例核心流水线中位数 355.426ms → 327.105ms（约 8.0%）；
Mapping 28.693ms → 0.220ms。其余约 80% 时间仍在 RenameIndex，不宣称大型工程性能问题已解决。

范围审查通过：不改 factory 接口/快照、schema、候选决策、SourceCatalog 或任何 gate 校验；
无全树长期缓存、全局缓存或新依赖。主 Agent 接受 T141，本轮两步实现结束。
