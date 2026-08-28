# T113：绑定死 generate 分支内的连接实参，或整体保留其符号

- 状态：`ACCEPTED`
- 主 Agent：Claude Fable 5
- 起始 HEAD：`6e71709`（T112 已 `ACCEPTED`，T111/T110/T109 已 `ACCEPTED`，T108 `BLOCKED`）
- 任务类型：`rename_index.py` 的 fail-open 面闭合
- 依据：[`T112 §14`](T112_gate_rename_audit.md) 的服务器门禁结果与根因实测

## 0. 这是一个已证实的功能性缺陷，阻塞上线

T112 的审计在 StCache 上首次运行即判定 `suspect`：gate 新增 **1514 个隐式 net**，
名字全是生成式 CSR 旧名。逐名验证：

```text
gold 2 处：  output logic [2:0]  AR_CACHE_CFG0_Ctrl_q,   ← 端口声明，已改名
             .q  (AR_CACHE_CFG0_Ctrl_q),                  ← 连接实参，未改名
gate 1 处：  .q  (AR_CACHE_CFG0_Ctrl_q),                  ← 残留 → 隐式 wire
```

该输出端口在 gate 中悬空。而 `strict_compile_passed=true`、`occurrence_coverage=1.0`、
`plaintext_leakage_rate=0.0`、`restored_byte_identical=true` **全部为真**——
这些指标只覆盖工具已识别的 occurrence，对"从未识别"无能为力。

## 1. 根因（已实测，不需重新发现）

模块**有定义**但实例化在**未选中的 generate 分支**内时，PySlang 为其创建
`UninstantiatedDefSymbol`，**不绑定连接实参**，且**不报任何错误**。

并排实测：

| 情形 | errors | `UninstantiatedDefSymbol` | 实参 AST 引用数 |
| --- | --- | --- | --- |
| A 有定义、活代码 | 无 | 0 | **1** 正常 |
| B 无定义（真黑盒） | `UnknownModule`（error） | 1 | **0** |
| **C 有定义、死 generate 分支** | **无** | **1** | **0** |

StCache 是情形 C：`semantic_errors=0` 且 `UninstantiatedDefSymbol=357`。

gate 状态复现（声明已改名、死分支实参留旧名）：

```text
errors = []            ← 严格编译查不出来
隐式 net = ['CFG_q']    ← 旧名以隐式 wire 出现
```

## 2. 单一目标

闭合该 fail-open：**一个符号只要在死源码中存在不可见的引用，就不得改名。**

关键在于 T109 已经证明"死源码里的 token 不可能有语义引用"，所以**不能靠绑定它们来解决**——
必须靠**识别其存在**并据此保留对应符号。

## 3. 冻结的做法

### 3.1 枚举死源码区域（复用 T109 已验证的机制）

`scripts/binding_coverage.py` 已实现并验证两种死区检测，本任务复用同一判定，
不得新增第二套：

| 形态 | 检测方式 |
| --- | --- |
| 设计单元从未 elaborate | CST 的 module/interface/package 声明跨度中，名字 token 不在任何 `InstanceBodySymbol`/`PackageSymbol` 的声明位置集合里 |
| elaborate 过的单元内含未选中 generate 分支 | `GenerateBlockSymbol.isUninstantiated == True`，取其 `syntax.sourceRange` |

### 3.2 死区内出现旧名即保留该符号

对每条本次**原本 eligible** 的记录（旧名 `n`）：

- 枚举全部死区内的 `TokenKind.Identifier` token（经 `getFullyOriginalLoc` 还原、逐个字节校验）；
- 若存在拼写 `n` 的 token，则该记录改为 `preserved`，reason 为新增的
  **`unelaborated_reference`**；
- 该保留是**逐记录**的，不得升级为组级回滚（T111 已确立的边界不得倒退）。

新 reason 必须加入 `docs/systemverilog_renaming_table.md` 与 README 的原因清单，
并加入 T112 §9 允许的 preserve 原因集合。

### 3.3 明确不做名字猜测

死区 token 无语义引用，所以**无法证明**它确实指向该符号——同名的另一个符号也可能。
因此本做法是**保守保留**而非绑定：宁可少改，不可改错。
这与项目既有原则一致（"不能证明唯一物理绑定时安全保留"），
且与 T109 §2 的逐符号完整性判据同向——那条判据的完整实现仍归后续任务。

## 4. 不包含的内容

- 不试图绑定死区内的引用（T109 已证明 PySlang 不提供该信息）；
- 不改动 `_apply_group_binding_issues` 的逐记录边界（T111 成果不得倒退）；
- 不改动 `_resolve_range_claims`、`_register_structs`；
- 不改变四个公开 category、`--encryption-rate`、mapping schema 2、SourceSet 语义、PySlang 编译配置；
- 不实现层次引用前缀、`NamedType` typedef 类型引用；
- 不新增名称搜索、文本扫描、正则解析或第二套 owner 推断（死区 token 枚举走 CST，非文本扫描）；
- 不运行 RISC-V-Vector Formal，不使用 blanket `unittest discover`。

## 5. 允许修改

- `rtl_obfuscator/rename_index.py`
- `tests/test_t113_unelaborated_reference.py`（新增）
- `tests/fixtures/t113_unelaborated_reference/**`（新增）
- `tests/test_t111_record_scope_preserve.py`、`tests/test_t110_binding_fixes.py`、
  `tests/test_t108_pyslang_rename_index.py`（仅在既有断言因本次改动必须调整时同步；
  逐条说明理由，不得放宽）
- `docs/systemverilog_renaming_table.md`、`README.md`（仅补 `unelaborated_reference` 原因）
- `docs/tasks/T112_gate_rename_audit.md`（仅把新 reason 加入 §9 允许集合）
- 本任务单、`docs/development/architecture/token_first_binding.md`

## 6. 固定 fixture

新增 `tests/fixtures/t113_unelaborated_reference/design.f`，其 `design.sv` 必须包含：

- 一个**有定义**的子模块，实例化在**未选中 generate 分支**内，其连接实参引用父模块的
  一个端口与一个内部信号 —— 复现 T112 §14.2 的情形 C；
- 同一父模块内另有**只在活代码中被引用**的端口与信号，用于证明它们仍然改名
  （保留必须是逐记录的，不得波及）；
- 一个从未 elaborate 的设计单元，其中引用了一个活代码中同名的符号，
  用于证明第一种死区形态同样触发保留；
- 一个 Yosys 可读的 Formal cone。

## 7. 机器可验收结果

本地 fixture 上 `--category all` 必须满足：

- 死分支实参引用到的端口与信号 `action == "preserve"`，`reason == "unelaborated_reference"`；
- 同一模块内只在活代码被引用的端口与信号仍 `action == "rename"`；
- 四组 `category_outcomes` 均 `rename > 0`；
- `strict_compile_passed=true`、`restored_byte_identical=true`；range audit 无重复、重叠、越界；
- **在该 fixture 的 gate 上运行 `scripts/gate_rename_audit.py` 必须 `verdict=clean`**
  且 `implicit_nets.gate_only == 0`；
- actual renamed gate 的 Formal 正例 exit 0 且 `formal_equivalence=pass`；
  固定功能负例 strict compile 通过但 Formal 非零。

第五条是本任务的核心验收：修复前该 fixture 的审计必须为 `suspect`，修复后必须为 `clean`。
**测试必须同时断言这两个方向**，证明修复真实有效而非绕过检查。

## 8. 固定验收命令（5 条）

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t113_unelaborated_reference tests.test_gate_rename_audit \
  tests.test_t111_record_scope_preserve tests.test_t110_binding_fixes \
  tests.test_t108_pyslang_rename_index tests.test_t108_public_core_flow \
  tests.test_public_cli tests.test_mapping_vnext tests.test_rewrite_vnext \
  tests.test_orchestration_vnext tests.test_restore_vnext -v

conda run -n rtl_obfuscation python -m unittest tests.test_binding_coverage -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/rename_index.py tests/test_t113_unelaborated_reference.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c 'from pathlib import Path; \
s=next(l for l in Path("docs/tasks/T113_unelaborated_reference.md").read_text().splitlines() if l.startswith("- 状态：")); \
assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t113_ready_for_review=pass")'
```

## 9. 服务器验收（上线门禁，两步）

第一步重新加密：

```sh
export PROJ=/home/lufengchi/workspace/ChipPlatform
OUT=/home/lufengchi/workspace/test/stcache_all_t113_001

python rtl_encrypt.py \
  --filelist "$PROJ/aic_ss/src/stcache/StCache.f" \
  --top StChCore \
  --category all \
  --include-dir "$PROJ/common/src/StLib/common" \
  --include-dir "$PROJ/common/src/StLib/impl_template/tsmc4" \
  --output-dir "$OUT"
```

第二步审计：

```sh
python scripts/gate_rename_audit.py \
  --map "$OUT/mapping.json" --gate-dir "$OUT" --gold-root "$PROJ" \
  --include-dir "$PROJ/common/src/StLib/common" \
  --include-dir "$PROJ/common/src/StLib/impl_template/tsmc4" \
  --json /home/lufengchi/workspace/test/stcache_gate_audit_t113.json
```

上线条件（全部满足才可上线）：

- 加密侧：无 `REFUSED_ATOMIC`；strict compile 与 byte-identical restore 均 true；
  四组均 `rename > 0`；preserve 原因只允许既有四种加上 `unelaborated_reference`；
- 审计侧：**`verdict=clean`，`implicit_nets.gate_only == 0`，`renamed_range_bytes.mismatched == 0`**。

预期代价：`rename` 会从 5931 下降，因为受死源码影响的符号转为保留。
**这是正确的方向**——用覆盖率换正确性。加密率下降多少由数据决定，不设目标值；
硬条件是四组仍 `rename > 0` 且审计 `clean`。

## 10. Formal verification

本任务产生改写 RTL，必须在本地 compact fixture 上完成一个 actual-gate 正例与一个固定功能负例。
StCache 规模的 Formal 不属于本任务；第 9 节的两步门禁是硬条件。

## 11. 执行记录

```text
status: READY_FOR_REVIEW
starting_head: 20c575d
contract_header_starting_head: 6e71709（任务单第 5 行记的是 T112 冻结时的 HEAD；
  本次开工时 main 的实际 HEAD 已推进到 20c575d，工作区干净。以实际 20c575d 为准。）
started: 2026-08-28
tool_form: /Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python
  （`conda run -n rtl_obfuscation` 在本机报 `__conda_exe: permission denied`，
   改用该环境的解释器绝对路径，环境本身与 CLAUDE.md 指定的 `rtl_obfuscation` 一致；
   主 Agent 复跑时若 conda 可用，可直接用任务单原文的 `conda run` 形式）
first_command: git status / git rev-parse HEAD
overlap_with_user_changes: 无（开工前 `git status` 为 clean）

changed_files:
  rtl_obfuscator/rename_index.py                        （+285 行，唯一产品改动）
  tests/test_t113_unelaborated_reference.py             （新增，10 个用例）
  tests/fixtures/t113_unelaborated_reference/design.f   （新增）
  tests/fixtures/t113_unelaborated_reference/design.sv  （新增）
  tests/fixtures/t113_unelaborated_reference/formal.f   （新增）
  tests/fixtures/t113_unelaborated_reference/formal_cone.sv（新增）
  docs/systemverilog_renaming_table.md                  （新增“死源码引用保留”一节）
  README.md                                             （新增 preserve reason 表）
  docs/tasks/T112_gate_rename_audit.md                  （§9 允许 preserve 原因集合）
  docs/development/architecture/token_first_binding.md  （新增 §2.2）
  docs/tasks/T113_unelaborated_reference.md             （本记录）
  允许列表外无任何改动；三个既有测试文件（T108/T110/T111）一行未改。

schema_or_behavior:
  新增 preserve reason `unelaborated_reference`，逐条生效。
  四个 category、`--encryption-rate`、mapping schema 2、SourceSet 语义、
  PySlang 编译配置、`RenameIndex`/`MappingVNext` 字段全部未变；
  唯一可观察差异是受死源码影响的记录 action 由 `rename` 变为 `preserve`。

implementation:
  `rename_index.py` 新增 7 个私有函数，全部在 `_apply_group_binding_issues`
  之后、单一入口 `_apply_unelaborated_references` 下调用：
    _syntax_nodes            从同一个 Compilation 取 CST（`getSyntaxTrees()`），不重新解析
    _buffer_file             buffer→SourceSet 相对路径的 memo（性能，无判定）
    _resolved_span           source range → 物理 (file,start,end)，先过 getFullyOriginalLoc
    _physical_declaration_key 名字 token 的物理位置身份
    _elaborated_unit_keys    InstanceBodySymbol / PackageSymbol 的声明位置集合
    _dead_source_regions     两种死区形态（复用 binding_coverage 的同一判定）
    _merge_regions           同文件嵌套死区合并为不相交区间，containment 一次 bisect
    _names_in_dead_source    死区内 Identifier token 枚举 + 逐字节校验
  调用点只有一处：`build_rename_index` 中
  `_apply_group_binding_issues(...)` 之后一行。

commands:
  1) python -m unittest tests.test_t113_unelaborated_reference
       tests.test_gate_rename_audit tests.test_t111_record_scope_preserve
       tests.test_t110_binding_fixes tests.test_t108_pyslang_rename_index
       tests.test_t108_public_core_flow tests.test_public_cli
       tests.test_mapping_vnext tests.test_rewrite_vnext
       tests.test_orchestration_vnext tests.test_restore_vnext -v
     → Ran 75 tests，OK，exit 0
  2) python -m unittest tests.test_binding_coverage -v
     → Ran 15 tests，OK，exit 0
  3) python -m py_compile rtl_obfuscator/rename_index.py
       tests/test_t113_unelaborated_reference.py
     → exit 0
  4) git diff --check HEAD
     → 无输出，exit 0
  5) T113 状态守卫
     → t113_ready_for_review=pass，exit 0

results:
  compact fixture `--category all`（rtl_encrypt.py，本地 fixture）：
    signals    status=preserved candidate=17 rename=15 preserve= 2 unsupported=0
    ports      status=preserved candidate=32 rename=22 preserve=10 unsupported=0
    interface  status=preserved candidate= 8 rename= 6 preserve= 2 unsupported=0
    struct     status=renamed   candidate= 3 rename= 3 preserve= 0 unsupported=0
    四组均 rename > 0；summary rename=46 preserve=14 unsupported=0
    strict_compile_passed=true  restored_byte_identical=true  modified_tokens=163
    reasons: unelaborated_reference=3、selected_top_boundary=9、
             hierarchical_prefix_unsupported=2（无未解释原因）
  逐记录判定（§7 前两条）：
    dead_port_o (ports)    preserve / unelaborated_reference  ← 死分支实参 + 活驱动
    dead_signal (signals)  preserve / unelaborated_reference  ← 只在死分支被引用
    shared_probe (signals) preserve / unelaborated_reference  ← 死区形态一（从未 elaborate）
    live_i / live_o / live_signal / private_probe → 仍 rename，reason=None
  range audit：无重复、无重叠、无越界，且每个 range 的字节等于其 name。

gate_audit（§7 第五条，本任务核心，两个方向都在测试里断言）：
  修复前（用本次 index 把 3 条 unelaborated_reference 记录翻回 rename，
  即 T113 之前产品实际发出的决策集，因为该保留是最后一条规则且只动仍 eligible 的记录）：
    gold 0/0  gate 0/0        ← 严格编译两侧都干净，缺陷对编译器不可见
    renamed_range_bytes: mismatched=0   ← 计划的编辑全部正确落盘
    implicit_nets: gold 0  gate 2  gate_only 2 = {dead_port_o, dead_signal}
    residual_old_names: 5
    VERDICT: suspect   exit 1
  修复后（同一 fixture，本次决策集；rtl_encrypt.py 发布的 gate 亦同）：
    implicit_nets: gate_only 0，gate_only_detail []
    renamed_range_bytes: checked>0  mismatched=0
    residual_old_names: 0
    VERDICT: clean     exit 0
  测试另外断言修复不是“让审计少看”：after 的 renamed_range_bytes.checked > 0、
  renamed_records.records > 0，且三个旧名仍物理存在于 gate 的死源码里。

test_is_load_bearing:
  把 rtl_obfuscator/rename_index.py 还原到 HEAD 后重跑新测试模块：
  10 个用例中 5 个失败（FAILED (failures=5)），包括核心验收用例
  test_gate_rename_audit_is_suspect_before_the_fix_and_clean_after_it。
  说明测试确实由本次修复承载，不是恒真断言。

formal_verification: PASS
  gold: tests/fixtures/t113_unelaborated_reference（formal.f，top t113_formal_top）
  正例 actual gate: rtl_encrypt.py --filelist formal.f --top t113_formal_top
    --category all（strict_compile_passed=true，modified_tokens>0，
    gate 的 formal_cone.sv 与 gold 字节不同，非 identity 比较）
  command: python scripts/formal_equivalence.py
    --gold-filelist <FIX>/formal.f --gold-root <FIX>
    --gate-filelist <gate>/design.f --gate-root <gate>
    --top t113_formal_top --seq 5
  exit: 0    json: {"formal_equivalence": "pass", "seq": 5, "top": "t113_formal_top"}
  固定功能负例: gate 内 t113_cone_mix 的唯一零字面量 1'b0 → 1'b1
    strict compile 仍为 0/0（catalog 与 top_overlay 均 parse=0 semantic=0），
    即真功能负例而非编译错误
  exit: 1（非零）  evidence: "unproven"; "equiv_status -assert"
  未运行 RISC-V-Vector Formal，未使用 blanket unittest discover。

boundaries:
  1. 保守保留、不做名字猜测：判定是按名字的。死区里拼写 n 的 token 无语义引用，
     无法证明它指向哪个 n，所以同名的活符号一律保留。代价是可能多保留同名符号，
     方向与 §3.3 一致（宁可少改，不可改错）。
  2. 死区 token 若其物理位置无法解析成 SourceSet 相对路径，或字节校验不通过，
     则不参与枚举。这与 `scripts/binding_coverage.py` 报告的
     `outside_source_set` / `byte_mismatch` 是同一条边界，本任务未改变它；
     理论上会少保留，属于未覆盖边界，由第 9 节服务器审计 `verdict=clean` 兜底确认。
  3. 未实现 T109 §2 的按名字完整性判据全貌，也未实现 `NamedType` typedef 类型引用
     绑定（token_first_binding.md §2.1 记录的 fail-open 面），两者仍归后续任务。
  4. `_apply_group_binding_issues`、`_resolve_range_claims`、`_register_structs`
     一行未改。新规则放在 `_apply_group_binding_issues` 之后，所以既不进入它的
     unknown-reason 分类，也不可能升级为组级回滚；issue 经 `_category_outcomes`
     正常上报（已断言 file/start/message 三元组存在）。
  5. 性能：新增一次 CST 遍历 + 一次 identifier token 过滤。本地最大 fixture 上
     CST 遍历 0.5–1.0 ms，token pass 0.6 ms；无死区时 token pass 直接短路为 0。
     buffer→file 已 memo（去掉 memo 时 t113 的 token pass 为 9.8 ms，加上后 0.6 ms）。
     StCache 规模的实际开销由第 9 节服务器门禁确认。

changed_existing_assertions: 无
  既有断言一条未改、一条未放宽。T108/T110/T111 三个测试文件保持原样即通过。
  另外单独核对过：本次改动前后，仓库里 14 个失败用例（test_t078/test_t088/
  test_t092/test_t096/test_t097/test_t073/test_formal_equivalence/
  test_vnext_product_surface）在 HEAD 20c575d 上原样失败，与本任务无关，
  未在本任务中触碰。

cleanup_candidates: 无

review_request:
  请复跑第 8 节五条命令，并执行第 9 节两步服务器门禁。
  预期 StCache 的 rename 从 5931 下降（受死源码影响的符号转为保留），
  硬条件是四组仍 rename > 0 且审计 verdict=clean、implicit_nets.gate_only == 0。
```

## 12. 主 Agent 独立验收记录

```text
reviewed_at: 2026-08-28
reviewed_head: 20c575d（与执行记录一致）
tool_form: /Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python
  （`conda run -n rtl_obfuscation` 在本机同样报 `__conda_exe: permission denied`，
   与子 Agent 记录一致，非其环境问题）

第 8 节五条门禁，主 Agent 亲自复跑：
  1) 11 模块 unittest              → Ran 75 tests，OK，exit 0
  2) tests.test_binding_coverage    → Ran 15 tests，OK，exit 0
  3) py_compile 两文件              → exit 0
  4) git diff --check HEAD          → 无输出，exit 0
  5) T113 状态守卫                  → t113_ready_for_review=pass，exit 0

边界核对：
  git status 仅含 README.md、docs/ 四个文件、rtl_obfuscator/rename_index.py，
  加两个未跟踪的新增（测试与 fixture）——全部在第 5 节允许列表内。
  `_apply_group_binding_issues`、`_resolve_range_claims`、`_register_structs` 的 diff 为零，
  第 4 节边界守住；T108/T110/T111 三个测试文件未出现在 diff 中，无断言被改动或放宽。
  唯一调用点确认在 build_rename_index 中 `_apply_group_binding_issues` 之后一行。

修复承载性（主 Agent 自行验证，不采信自报）：
  把 rtl_obfuscator/rename_index.py 还原到 HEAD 后重跑新测试模块 → FAILED (failures=5)/10，
  含核心验收用例；还原回交付版后与交付文件逐字节相同。
```

### 12.1 主 Agent 亲手在发布的 gate 上跑审计

第 7 节第五条是本任务的全部意义，因此不经测试封装，直接用公开 CLI 发布 gate 再审计：

```text
rtl_encrypt.py --category all → rename 46  preserve 14
  strict_compile_passed=true  restored_byte_identical=true
gate_rename_audit.py → verdict=clean  exit 0
  implicit_nets: gold 0  gate 0  gate_only 0
  renamed_range_bytes: checked 163  mismatched 0
  residual_old_names: 0     renamed_records: 46（44 个不同旧名）
```

`checked=163`、`records=46` 同时为正，证明 clean 不是"少改所以少看"换来的。

### 12.2 主 Agent 补做的判别：保留由真 token 驱动，而非文本命中

交付的 fixture **无法**区分这一点。实测其 `design.sv` 中 `dead_port_o` **同时**出现在死分支的
连接实参和该分支内的注释里（fixture 头部"没有标识符写在注释里"的自述因此不成立，
`dead_signal` 才是干净样本）。文本扫描式实现与正确的 CST 实现在该记录上表现相同。

主 Agent 另建判别用例：把三个**活的、可改名**的符号名只放在死区里文本可见的位置——
未选中分支内的注释、从未 elaborate 单元内的注释、死代码中的字符串字面量：

```text
live_signal    owner=t113_branch       support=eligible   ← 仍改名
live_o         owner=t113_branch       support=eligible   ← 仍改名
private_probe  owner=t113_shared_user  support=eligible   ← 仍改名
s_out          owner=t113_shared_user  support=eligible   ← 仍改名（字符串字面量）
dead_signal / shared_probe             preserved / unelaborated_reference
unelaborated_reference 保留集合不变，仍为 3 条
```

结论：实现确实只枚举 CST 的 `Identifier` token，注释与字符串字面量不参与判定，
第 4 节"不新增文本扫描"的边界成立。

### 12.3 决定性证据来自本地 RISC-V-Vector，而不是 fixture

fixture 只有 3 条保留。`rtl_samples/RISC-V-Vector`（project-root，top `vector_top`，
19 个源文件，§5.3 记录 39 个死 generate 分支）是手边最接近 StCache 的样本。
主 Agent 用同一条流水线跑 before/after，唯一差异是把新规则置空（不改仓库）：

```text
category      cand   rename B   rename A    delta
signals        675        675        569       -106
ports          359        348        239       -109
interface        0          0          0         +0   ← 该设计无 interface，非回退
struct          73         67         55        -12
total rename  1090 → 863（-227，保留 79.2%）
两侧 strict_compile=(0,0,0,0)、byte_identical=true

gate 审计：
  before  verdict=suspect  exit 1  implicit_nets gold 5  gate 15  gate_only 11
  after   verdict=clean    exit 0  implicit_nets gold 5  gate  5  gate_only  0
  residual_old_names 60 → 11
```

**这条数据比 fixture 重要得多：项目自带的样本在修复前本身就是 `suspect`。**
同一个缺陷一直活在本地 RISC-V-Vector 上，历次验收全绿而无人发现——因为在 T112 之前
没有任何指标看得见它。修复后该样本转为 `clean`。

代价数量级也由此可预估：本地 -21%。StCache 的实际下降由第 9 节数据决定，不设目标值。

### 12.4 执行记录中一处数字不准（已核对，非缺陷）

执行记录写 `rename_index.py（+285 行）`，`git diff --stat HEAD` 实测为 **+332 行**
（`541 insertions` 为含文档的合计）。代码本身与描述一致，仅该行数不准，此处更正，不退回。

## 13. 验收中新发现的审计器缺陷（属 T112，不属本任务）

主 Agent 在 12.3 的 before 侧看到一个不符合"旧名残留"形状的命中，未按经验推断而直接追查：

```text
gate_only 名单含 gbaYDyE7cpE3tR3iEW6N —— 一个新混淆名，不是旧名
追查得：其旧名为 vmu 模块的 valid，而 valid 在 vmu.sv 中根本没有声明
        （8 处全是端口标签与使用），它本身就是 gold 的一个隐式 net
```

根因在 `scripts/gate_rename_audit.py`：翻译 gold 隐式 net 用的 `rename_map` 是
**全局 `旧名 → 新名` 字典**，而同一拼写在不同作用域会被改成不同新名。
RISC-V-Vector 上实测 **206 个旧名被改成多于一个新名**（`i` 有 27 个、`clk` 有 15 个、
`valid` 有 5 个）。字典只留最后一个，于是 gold 的隐式 net 被翻译成错误的新名，报出假 `gate_only`。

方向判定：该缺陷**偏保守**——产生假 `suspect`，不会产生假 `clean`，
因此它从未放行过错误的 gate，T112 §14 在 StCache 上的 `suspect` 结论不受影响
（那 1514 条全是旧名，且 T113 的机制已独立证实）。

但它有两个现实代价，必须在跑第 9 节之前讲清楚：

1. StCache 的 `implicit_nets.gold=17`，其中任何一个若同时是"被改成多个新名"的拼写，
   审计就会在一个正确的 gate 上报假 `suspect`，白费一次服务器往返；
2. 更危险的是**误读**：假 `suspect` 会被当成 T113 没修好。

判别规则（服务器结果按此读）：`gate_only_detail` 里的名字若是**旧名**，是真漏改；
若是**新混淆名**，是本节的审计器缺陷。

修复归 T114，本任务第 5 节不允许改 `scripts/gate_rename_audit.py`，故不在此处顺手改。
