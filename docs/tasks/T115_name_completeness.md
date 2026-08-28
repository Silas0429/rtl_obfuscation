# T115：把逐符号完整性判据搬进产品，作为保留门禁

- 状态：`ACCEPTED`
- 主 Agent：Claude Fable 5
- 起始 HEAD：`3f3b343`（T113、T114 均 `ACCEPTED`）
- 任务类型：`rename_index.py` 的保留门禁改为可证明的完整性判据
- 依据：[`token_first_binding.md §2`](../development/architecture/token_first_binding.md)、T113 §9 的服务器结果

## 0. 为什么不再逐个形状修

T113 交付后重跑 StCache 的服务器门禁：

```text
rename 4728  preserve 2356  unsupported 18
strict_compile_passed=true  restored_byte_identical=true
renamed_range_bytes: checked 15078  mismatched 0
implicit_nets: gold 17  gate 1341  gate_only 1324
gold_fallback_to_old_name 6（均在其他文件，与本缺陷无关）
VERDICT: suspect
```

T113 消掉了 190 条（1514 → 1324），但剩余 1324 条**全在** `aic_ss/src/stcache/src/Csr/csr_behvr.sv`，
且全是旧名（`AR_CACHE_CFG0_Ctrl_q` / `_qs` / `_wd` / `_we` / `_addrhit` 这类生成式 CSR 名）。

`residual_old_names` 的偏移量给出了形态：`reg_we` 在 4044/4055、`reg_re` 在 4093/4104、
`reg_wdata` 在 4191/4202、`reg_wstrb` 在 4240/4251——**相距 11 字节的成对出现**，
即 `.reg_we    (reg_we)` 这种对齐排版的具名端口连接，标签与实参都留着旧名，
而该信号在 `csr_behvr` 内的声明已被改名。

已排除的两种解释（不要重新排查）：

- **不是 T114 的假报**：命中的全是旧名；`gold_fallback_to_old_name` 仅 6 条且在别的文件。
- **不是真黑盒（T112 §14.2 情形 B）**：`UnknownModule` 未被抑制，它进 `semantic_errors`，
  且 `expand_hierarchy` 会把缺失模块的文件拉进闭包，真找不到则以 `UNRESOLVED_MODULE` 硬失败。
  StCache `semantic_errors=0`，故不是黑盒。

**本任务不去定性这第三种形态。** 连续三轮"发现形状 → 加一条兼容"已经证明该路径不收敛，
这也正是用户最初质疑的问题。改为实现一条与形状无关的判据。

## 1. 单一目标

把 [`token_first_binding.md §2`](../development/architecture/token_first_binding.md) 的判据
落进产品，作为改名的前置条件：

> 对旧名为 `n` 的符号 S：令 T = 源码集合中所有拼写 `n` 的物理 identifier token。
> 当且仅当 T 中不存在**未归属** token 时才改名 S。

未归属即：既没有归属给任何语义引用，也没有归属给任何声明。
只要存在一个未归属的同名 token，就保留所有拼写 `n` 的记录。

这条判据与形状无关，因此**一次性覆盖**已知的三种 fail-open
（死 generate 分支实参、`csr_behvr.sv` 的未定性形态、§2.1 的 `NamedType` typedef 成员类型引用），
以及一切未来未知形状。代价是覆盖率，方向由用户已确认（不要求完全加密）。

## 2. 冻结的做法

### 2.1 复用已验证的机制，不得新增第二套

`scripts/binding_coverage.py` 已在 StCache（154 文件、61659 token、`byte_mismatch=0`）
与 RISC-V-Vector 上验证了全部所需机制，本任务复用同一判定：

| 机制 | 现有实现 |
| --- | --- |
| CST 全部 `TokenKind.Identifier` token 枚举 + 逐字节校验 | `_collect_tokens` |
| AST 全部引用节点的 `sourceRange` + 目标 | `_collect_references` |
| 目标身份按**物理声明位置**（不得用 `id()`，见 §5.1） | `_declaration_identity` |
| 最小区间归属规则 | `_join` |
| 声明归属 | `_collect_declarations` |
| 按名字统计 `accounted` / `unaccounted` | `_completeness` |

产品侧已有 `_apply_unelaborated_references`（T113）走通了"从同一个 Compilation 取 CST +
`getFullyOriginalLoc` 还原 + 逐字节校验"的路径，本任务在同一处扩展，不新建入口。

### 2.2 新 reason 与既有 reason 的优先级

新增 preserve reason **`incomplete_name_coverage`**。

T113 的 `unelaborated_reference` 更具体（明确指出旧名写在死源码里），诊断价值更高，
因此**先跑 T113 的规则**，再跑本判据；已被 T113 保留的记录不再改 reason。
两条规则都是逐记录生效，T111 建立的边界不得倒退。

新 reason 必须加入 `docs/systemverilog_renaming_table.md`、README 原因清单，
以及 T112 §9 允许的 preserve 原因集合。

### 2.3 三层分母的口径必须与探测器一致

探测器的教训（§5.2）必须继承：**未 elaboration 的源码里的 token 一律计为未归属**——
这正是 T113 已经在做的事，两条规则同向，不冲突。

不得为了提高覆盖率而把某类 token 排除在分母之外。任何排除都必须是
"该 token 不可能是本次改名目标"的**语言事实**（例如 `SystemIdentifier` 是语言内建），
不得是"该 token 我们暂时处理不了"。

### 2.4 性能必须实测并记录

全 token 枚举在 StCache 规模上是 61659 个 token、154 个文件。
探测器已证明可行，但产品路径每次加密都要跑，必须记录实测耗时。
若超过 60 秒，先记录数字再判断，不得自行降级判定。

## 3. 不包含的内容

- 不去定性 `csr_behvr.sv` 的具体形态（本任务的意义就是不需要它）；
- 不试图**绑定**任何当前未绑定的 occurrence（那是提高覆盖率，不是本任务）；
- 不改动 `_apply_group_binding_issues` 的逐记录边界（T111 成果不得倒退）；
- 不改动 `_resolve_range_claims`、`_register_structs`、T113 的 `_apply_unelaborated_references`
  的判定（可在其后追加新规则，不得修改其行为）；
- 不改变四个公开 category、`--encryption-rate`、mapping schema 2、SourceSet 语义、PySlang 编译配置；
- 不修改 `scripts/gate_rename_audit.py`、`scripts/binding_coverage.py`
  （可 import 或复制其判定逻辑，但不得改动这两个只读工具的行为）；
- 不放宽任何既有断言；
- 不运行 RISC-V-Vector Formal，不使用 blanket `unittest discover`。

## 4. 允许修改

- `rtl_obfuscator/rename_index.py`
- `tests/test_t115_name_completeness.py`（新增）
- `tests/fixtures/t115_name_completeness/**`（新增）
- `tests/test_t113_unelaborated_reference.py`、`tests/test_t111_record_scope_preserve.py`、
  `tests/test_t110_binding_fixes.py`、`tests/test_t108_pyslang_rename_index.py`
  （仅在既有断言因覆盖率下降必须同步时；**逐条说明理由，不得放宽断言强度**。
   把"某符号改名"改成"某符号保留"是口径同步；把"四组均 rename > 0"删掉是放宽，禁止）
- `docs/systemverilog_renaming_table.md`、`README.md`（仅补新 reason）
- `docs/tasks/T112_gate_rename_audit.md`（仅把新 reason 加入 §9 允许集合）
- 本任务单、`docs/development/architecture/token_first_binding.md`

## 5. 固定 fixture

新增 `tests/fixtures/t115_name_completeness/`，必须包含两个**互相独立**的形态：

- **形态一，已知的 fail-open**：`token_first_binding.md` §2.1 记录的最小复现——
  一个 typedef 同时用作变量/端口类型与另一个 struct 的**成员类型**。
  该 `NamedType` 引用不被绑定、不产生任何 issue，声明却照改，改后 gate 严格编译失败。
  **修复前**：`write_gate_vnext` 报 `CATALOG_SEMANTIC_FAILED`（或该路径产出 `REFUSED_ATOMIC`）；
  **修复后**：该 typedef 报 `incomplete_name_coverage` 并保留，gate 严格编译通过。
  这一对是本任务的核心验收：它证明判据抓住了一个 T113 抓不到的、独立形态的 fail-open。
- **形态二，不得波及**：同一设计中另有一个**全部 token 都已归属**的符号（同类别），
  必须仍然改名，证明保留是逐记录的而非整组。
- 一个 Yosys 可读的 Formal cone。

另外必须断言：形态一的保留原因是 `incomplete_name_coverage` 而**不是**
`unelaborated_reference`——否则说明它是被 T113 的规则顺带盖住的，本判据没有被真正验证。

## 6. 机器可验收结果

- 形态一的 typedef `action == "preserve"`、`reason == "incomplete_name_coverage"`；
- 形态二的符号仍 `action == "rename"`；
- 四组 `category_outcomes` 均 `rename > 0`；
- `strict_compile_passed=true`、`restored_byte_identical=true`；range audit 无重复、重叠、越界；
- 该 fixture 的 gate 上 `scripts/gate_rename_audit.py` 必须 `verdict=clean`
  且 `implicit_nets.gate_only == 0`；
- 修复前该 fixture 必须失败（严格编译失败或 `REFUSED_ATOMIC`），修复后必须通过；
  **测试必须同时断言这两个方向**；
- actual renamed gate 的 Formal 正例 exit 0 且 `formal_equivalence=pass`；
  固定功能负例 strict compile 通过但 Formal 非零。

## 7. 固定验收命令（5 条）

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t115_name_completeness tests.test_t113_unelaborated_reference \
  tests.test_gate_rename_audit tests.test_t111_record_scope_preserve \
  tests.test_t110_binding_fixes tests.test_t108_pyslang_rename_index \
  tests.test_t108_public_core_flow tests.test_public_cli tests.test_mapping_vnext \
  tests.test_rewrite_vnext tests.test_orchestration_vnext tests.test_restore_vnext -v

conda run -n rtl_obfuscation python -m unittest tests.test_binding_coverage -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/rename_index.py tests/test_t115_name_completeness.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c 'from pathlib import Path; \
s=next(l for l in Path("docs/tasks/T115_name_completeness.md").read_text().splitlines() if l.startswith("- 状态：")); \
assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t115_ready_for_review=pass")'
```

## 8. 本地回归测量（必做，记录实际数字）

在 `rtl_samples/RISC-V-Vector`（project-root，top `vector_top`）上发布 gate 并审计，
记录四组 rename/preserve、新 reason 计数、`verdict`、`implicit_nets` 三个计数、
以及 §2.4 的实测耗时。

T113/T114 之后该样本的基线是 `rename 863 / preserve 244`、`verdict=clean`、`gate_only=0`。
本判据会让 rename **进一步下降**，这是预期的；`verdict` 必须仍为 `clean`。
硬条件是**任何 candidate > 0 的组不得跌到 `rename = 0`**。

（原文写"四组仍 `rename > 0`"，但 RISC-V-Vector 没有 interface，
`interface` 的 candidate 恒为 0，该条件在该样本上数学上不可满足。
这是主 Agent 的契约缺陷，与 T110 §1/§8 vs §3 同类，见 §12.6。）

不运行该样本的 Formal，不运行 `tests.test_risc_v_vector_project_root`。

## 9. Formal verification

本任务产生改写 RTL，必须在本地 compact fixture 上完成一个 actual-gate 正例与一个固定功能负例。
StCache 规模的 Formal 不属于本任务。

## 10. 服务器验收（上线门禁，两步）

```sh
export PROJ=/home/lufengchi/workspace/ChipPlatform
OUT=/home/lufengchi/workspace/test/stcache_all_t115_001

python rtl_encrypt.py \
  --filelist "$PROJ/aic_ss/src/stcache/StCache.f" --top StChCore --category all \
  --include-dir "$PROJ/common/src/StLib/common" \
  --include-dir "$PROJ/common/src/StLib/impl_template/tsmc4" \
  --output-dir "$OUT"

python scripts/gate_rename_audit.py \
  --map "$OUT/mapping.json" --gate-dir "$OUT" --gold-root "$PROJ" \
  --include-dir "$PROJ/common/src/StLib/common" \
  --include-dir "$PROJ/common/src/StLib/impl_template/tsmc4" \
  --json /home/lufengchi/workspace/test/stcache_gate_audit_t115.json
```

上线条件：四组均 `rename > 0`；无 `REFUSED_ATOMIC`；strict compile 与 byte-identical restore 均 true；
**`verdict=clean`、`implicit_nets.gate_only == 0`、`renamed_range_bytes.mismatched == 0`**。

预期代价：T109 在 StCache 上量到 `renameable_name_ratio = 1035 / 3637 = 28.46%`，
所以 rename 会从 4728 显著下降。**不设目标值**；判据的意义是把"编译过但功能错"
换成"改得少但可证明正确"。

## 11. 执行记录

```text
status: IN_PROGRESS
starting_head: c1ca685
tool_form: /Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python
           （`conda run -n rtl_obfuscation` 在本机以 `__conda_exe: permission denied` 失败，
            与 T110–T114 相同的替代形式；PySlang 11.0.0、CPython 3.12.13）
first_command: git rev-parse HEAD -> c1ca685125118dd140789c38e9b9f1181c7efc1d（工作区干净）
```


## 12. 主 Agent 独立验收记录

```text
reviewed_at: 2026-08-28
reviewed_head: c1ca685
tool_form: /Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python

第 7 节五条门禁，主 Agent 亲自跑：
  1) 12 模块 unittest              → Ran 91 tests，OK，exit 0（清空全部 __pycache__ 后复跑仍 OK）
  2) tests.test_binding_coverage    → Ran 15 tests，OK，exit 0
  3) py_compile 两文件              → exit 0
  4) git diff --check HEAD          → 无输出，exit 0
  5) T115 状态守卫                  → t115_ready_for_review=pass，exit 0

T115 自身模块单跑：Ran 11 tests，OK
  Formal 正例 exit 0、{"formal_equivalence": "pass", "seq": 5, "top": "t115_formal_top"}
  Formal 负例 exit 1、"unproven; equiv_status -assert"（1'b0 → 1'b1 in t115_cone_mix）

边界核对：改动仅 README、docs 四个文件、rtl_obfuscator/rename_index.py，
  加两个未跟踪的新增（测试与 fixture），全部在第 4 节允许列表内。
  `tests/test_t110_binding_fixes.py`、`test_t111_*`、`test_t108_*`、`test_t113_*`
  一行未改 —— 既有断言零同步、零放宽，且在新判据下原样通过。
```

### 12.1 流程偏差：本任务的收尾验证与一处修复由主 Agent 完成（显式记录）

子 Agent 完成了实现、fixture 与测试（`rename_index.py` +439/-7、
`tests/test_t115_name_completeness.py` 776 行 11 用例、fixture 四个文件、四份文档），
但在"重跑完整测试面与 §8 回归"之前被停止。用户在被告知代价后选择由主 Agent 直接收尾。

代价是本任务的**验证环节**失去"实现者与验收者分离"的双重检查（实现环节仍是分离的），
且 §12.2 记录的那处间歇缺陷修复也由主 Agent 直接完成，因此该修复没有第二人复审。
如实记录，不隐藏。为部分补偿，主 Agent 额外做了 12.3 的两项作弊复现，
并对该修复做了 40 次重复运行的统计验证而非单次通过。

### 12.2 一个真实的间歇缺陷，以及主 Agent 中途一次错误的撤回

这一节记录三步，包括主 Agent 自己判断反复的过程，因为过程本身是结论的一部分。

**第一步，观测。** 首次跑 §7 第一条命令得到 `Ran 91, FAILED (failures=3)`，
全在 `test_t110_binding_fixes`：`nested_same_name` 变 `preserved`、struct `preserve` 0→3、
`incomplete_name_coverage` 不在该测试的允许集合。据此判定为"顺序相关的状态泄漏"。

**第二步，错误的撤回。** 随后 15 次以上运行全过，逐个 T115 用例配 T110 的十组二分全部 0 失败，
进程内两种顺序直接建 T110 索引都是 0 条 `incomplete_name_coverage`，
清空 `__pycache__`（发现同时存在 `cpython-312` 与 `cpython-313` 两份字节码）后也通过。
主 Agent 据此**撤回了缺陷判断，记为"不可复现的观测"**。

**这次撤回是错的。** 真实原因是那些实验的统计功效不足：缺陷发生率约 1/5，
而每组只跑 1 到 5 次——6 次全过的概率约 33%，所以"某组不触发"这个结论根本站不住。
后续加大样本立刻复现：

```text
T115 产品代码，11 个模块（不含 T115 自己的测试），10 次   → 2/10 失败
  且命中模块会变：一次 test_t110_binding_fixes，一次 test_t111_record_scope_preserve
HEAD 产品代码（无 T115），同样 11 个模块，10 次            → 0/10 失败
```

命中模块会变这一点排除了"某个测试写坏了 fixture"（已另外用 fixture 校验和确认未被改动），
并把范围锁定为**产品代码引入的进程级不确定性**。

**第三步，定性并修复。** 根因在 `_aggregate_field_symbols` 的去重守卫：

```python
visited: set[int] = set()      # 按 id(canonical) 去重
```

`id()` 只在对象**同时存活**时唯一，而 PySlang 每次属性访问都可能新建 Python 包装对象。
包装对象被回收后 CPython 复用其地址，于是一个从未访问过的聚合类型可能拿到已回收对象的
`id`，被误判"已访问"而整个跳过——它的字段声明不进归属集合，同名 token 变成未归属，
冒出没有依据的 `incomplete_name_coverage` 保留。是否发生取决于分配历史，
也就是**同进程里之前跑过什么**，因此表现为间歇且命中位置漂移。

这正是 [`token_first_binding.md §5.1`](../development/architecture/token_first_binding.md)
已经写明的禁令（身份必须用物理声明位置，绝不用对象身份）在一个去重守卫里被重新引入。
讽刺的是 `_reference_spans` 的 docstring 正确复述了这条禁令，而它自己的回退分支
`("$unresolved", id(target))` 犯了同一个错。

修复两处，都朝"证不出身份就保留"的安全方向：

| 位置 | 修法 |
| --- | --- |
| `_aggregate_field_symbols` | 新增 `alive: list[Any]`，把每个已访问对象强引用住，使其 `id` 在遍历期间不可能被复用。若 PySlang 确实每次返回新包装，守卫只是不再命中、重复做功，代价是时间而非正确性 |
| `_reference_spans` | 物理位置取不到时**丢弃该引用**，不再伪造 `id()` 身份。伪造身份的危险方向是两个不同声明碰撞成同一身份 → 最窄区间不再打平 → token 被归属给错误的 owner → 改了不该改的名 |

修复后的验证（修复前是 2/10）：

```text
11 个模块 × 20 次   → 0/20 失败
12 个模块 × 20 次   → 0/20 失败
```

按 1/5 的发生率，20 次全过的偶然概率约 1.2%，两组合计约 1.5e-4，故认定修复成立。
RISC-V-Vector 连跑 3 次结果完全一致（`rename=836 preserve=271`，各组与 reason 计数逐项相同），
说明修复没有改变判定结果，只是让它变得确定。

**方法论教训，值得写进流程：** 对疑似间歇缺陷做二分，每组样本数必须先按估计发生率定，
否则"通过"只是没抽中。本项目此前的合同错误都是"从单样本推断机制"
（T108 §14、T110 §2.4），这次是同一个毛病的另一种形态：**从单样本推断"没有缺陷"**。

### 12.3 主 Agent 复现两种"收窄分母"的错误修法

§2.3 的全部效力取决于分母是否诚实，所以主 Agent 不只读断言，而是把错误修法写出来实跑：

```text
作弊 A：把 name.endswith("_t") 的 token 排除出分母（"类型名另有处理"）
        → Ran 11, FAILED (failures=7)
        含 test_the_token_denominator_is_every_physical_spelling_in_the_source、
        test_exactly_one_token_of_this_fixture_is_unattributed、
        test_shape_one_is_preserved_...、公开 CLI 用例
        与子 Agent 记录的"7 个失败"完全一致，独立复现成立。

作弊 B：把 unverified.add(name) 三处改为静默丢弃（"定位不到就不算"）
        → Ran 11, OK          ← 全部通过，测试不设防
```

作弊 A 被牢牢守住：ground truth 是**对 fixture 文件的原始字节搜索**，不经过 PySlang，
任何收窄都会让某个拼写对不上。这是正确的做法。

作弊 B 暴露一个真实盲区，见 12.5。

### 12.4 第 8 节回归，主 Agent 实测

`rtl_samples/RISC-V-Vector`（project-root，top `vector_top`，19 文件）：

```text
category      cand   rename   preserve
signals        675      542        133
ports          359      239        120
interface        0        0          0     ← 该设计无 interface（改动前后一致）
struct          73       55         18
total rename=836  preserve=271        （T113/T114 基线 863/244，即 -27）
reasons: unelaborated_reference 227、incomplete_name_coverage 27、
         selected_top_boundary 11、outside_top_closure 6
strict_compile=(0,0,0,0)   byte_identical=True

审计：verdict=clean   exit 0
  implicit_nets: gold 5  gate 5  gate_only 0
  gold_fallback_to_old_name 1（valid @ rtl/vector/vmu.sv:20220，与 T114 §11.2 同一条）
  renamed_range_bytes: checked 4061  mismatched 0
  residual_old_names: 4              （T114 基线为 11，本次下降）
```

下降的 27 条全部落在 `signals`，全部原因为 `incomplete_name_coverage`，
与文档 §2.3 已写的数字一致。无回退，`residual_old_names` 还改善了。

§2.4 耗时：`build_rename_index` 在该设计上全程 **2.71s**（19 文件）。
StCache 是 154 文件、61659 token，约 8 倍规模，因此预期在几十秒量级，
远低于 §2.4 的 60 秒判断线；确切数字由第 10 节服务器门禁给出。

### 12.5 未覆盖边界（主 Agent 新发现，需记录）

**`unverified` 路径没有断言守着。** fixture 上 `unverified == frozenset()`，
即没有任何定位不到或字节校验不过的 token，所以"定位不到 → 按未归属 → 保留"这条
安全默认从未被走到。产品行为今天是正确的（12.3 作弊 B 的改动在本 fixture 上行为等价），
但将来有人把它改成静默丢弃，不会有任何测试失败——而丢弃是 fail-open 方向，
正是造成 T112/T113/T115 这一连串问题的那一类错误。

不在本任务补：要构造一个 PySlang 定位不到的 token 并不直接，
`scripts/binding_coverage.py` 把 `outside_source_set` / `byte_mismatch` 也列为边界而非可控输入。
应另立任务，或在实现层面把该分支改为可注入以便断言。

### 12.6 主 Agent 自己的契约缺陷（第三次同类错误，如实记录）

第 8 节写"硬条件是四组仍 `rename > 0`"。但 RISC-V-Vector **没有 interface**
（`interface` candidate=0，改动前后都是 0），该条件在这个样本上数学上不可满足。

正确表述应为"任何 candidate > 0 的组不得跌到 rename = 0"。

这与 `token_first_binding.md §6.2` 已记录的 T110 §1/§8 vs §3 是**同一类错误**：
契约要求了它自己边界所禁止的结果。同类错误在本项目已出现三次
（T108 §14、T110 §2.4、T110 §1/§8），本条是第四次，均由主 Agent 造成。
判据条件必须按**可满足性**校验，不能只按语义直觉写。

`main_result: ACCEPTED`（判据本身与其验证均成立）
`ship_decision: 服务器门禁（第 10 节）未跑，上线仍阻塞`
