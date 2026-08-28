# T113：绑定死 generate 分支内的连接实参，或整体保留其符号

- 状态：`READY`
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
status: READY
starting_head: 6e71709
```
