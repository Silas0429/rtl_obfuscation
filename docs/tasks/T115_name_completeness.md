# T115：把逐符号完整性判据搬进产品，作为保留门禁

- 状态：`READY`
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
硬条件是四组仍 `rename > 0`。

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
status: READY
（子 Agent 开工前改为 IN_PROGRESS 并记录 starting_head、tool_form、first_command）
```
