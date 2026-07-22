# T040：统一 semantic catalog 与 module owner registry

- 状态：`ACCEPTED`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 所属重构阶段：R2-A
- 前置任务：T039 `ACCEPTED`，交付提交 `5a8b073`
- 设计依据：`docs/three_mode_refactor_plan.md` 第 3、4、6 节
- 执行规范：`docs/refactor_subagent_protocol.md`
- 验收类型：SymbolGraph/range 的前置 semantic catalog
- Formal verification：`N/A`，本任务不产生 rewritten RTL

## 1. 项目目标与本任务位置

项目最终只保留以下一条核心流水线：

```text
single-file -----------+
filelist --------------+--> SourceSet --> semantic catalog --> SymbolGraph
project-root adapter --+                                      --> RewritePolicy
                                                               --> mapping/rewrite/audit
```

T039 已统一三个输入入口。T040 只完成 R2 的第一块基础：针对一个 SourceSet 建立严格 catalog
semantic view、可选 selected-top overlay，以及两个视图共用的 module source-owner registry。

本任务不收集 parameter、genvar、signal 或其他可重命名 symbol。下一任务只有在 T040 验收后，才可
在同一 owner registry 上增加 source symbol、occurrence 和 provenance。

## 2. 单一目标

新增 `rtl_obfuscator/source_catalog.py`，对任意 T039 SourceSet：

1. 使用全部 `compile_order` 建立严格 catalog compilation；
2. SourceSet 提供 top 时，使用同一文件、include dirs 和 defines 建立 selected-top overlay；
3. 为每个物理 module declaration 建立且只建立一个稳定 `ModuleOwner`；
4. 将 catalog view 和 top overlay 中的 semantic module definition 映射回同一 owner id；
5. 输出确定、可序列化、可进行 range/owner 审计的 report。

T040 只证明 module owner 与 top-closure module identity，不实现 SymbolGraph occurrence collector。

## 3. 固定公开 API

`rtl_obfuscator/source_catalog.py` 提供：

```python
@dataclass(frozen=True)
class SourceRange:
    file: str
    start: int
    end: int

@dataclass(frozen=True)
class ModuleOwner:
    owner_id: str
    name: str
    declaration: SourceRange
    in_top_closure: bool
    is_selected_top: bool

@dataclass(frozen=True)
class SourceCatalog:
    schema_version: int
    source_set: SourceSet
    modules: tuple[ModuleOwner, ...]
    top_closure_owner_ids: tuple[str, ...]
    catalog_compilation: object
    catalog_root: object
    catalog_source_manager: object
    top_compilation: object | None
    top_root: object | None
    top_source_manager: object | None

    def to_report(self) -> dict[str, object]: ...

class SourceCatalogError(ValueError):
    code: str
    message: str
    file: str | None
    start: int | None

def build_source_catalog(source_set: SourceSet) -> SourceCatalog: ...
```

PySlang 对象必须标记为 `repr=False, compare=False`，不得进入 `to_report()`。T040 不要求从
`rtl_obfuscator/__init__.py` 重导出这些 API。

## 4. 两个语义视图的冻结规则

### 4.1 catalog view

- 按 `source_set.compile_order` 将全部 `.sv` 作为一个 compilation unit 编译；
- 使用 `source_set.include_dirs` 和 `source_set.defines`；
- 不设置 explicit top，使 PySlang 建立全 SourceSet catalog view；
- module catalog 覆盖 `ordered_source_files` 中每个物理 module declaration，包括 filelist 中
  closure 外文件和 top-closure 文件内未实例化的 module；
- 同一 module definition 被实例化多次时仍只有一个 ModuleOwner；
- parse 或 semantic error 必须 fail-closed，不返回部分 catalog。

### 4.2 selected-top overlay

- 仅当 `source_set.top` 非空时建立；
- 使用与 catalog view 完全相同的文件顺序、include dirs、defines 和 compilation-unit 语义；
- 唯一区别是设置 `topModules={source_set.top}`；
- 从 top instance 递归取得实际 reachable module definitions；
- repeated instance 按 definition declaration 去重；
- 不能用 `top_closure_files` 直接推断 module closure，因为一个文件可以同时包含 reachable 和
  unreachable module；
- overlay definition 必须依据 declaration source range 映射到 catalog 的 ModuleOwner，禁止只按
  module name 或 instance name 匹配。

### 4.3 无 top

- `top_compilation`、`top_root`、`top_source_manager` 为 `None`；
- `top_closure_owner_ids=()`；
- 所有 ModuleOwner 的 `in_top_closure` 和 `is_selected_top` 都为 `False`。

## 5. owner 与 range 不变量

### 5.1 SourceRange

- `file` 使用 source-root-relative POSIX path；
- `start/end` 是 UTF-8 source byte offset，满足 `0 <= start < end <= len(source)`；
- `source[start:end] == module_name.encode("utf-8")`；
- 只记录 module identifier token，不记录整个 declaration syntax。

### 5.2 owner_id

固定格式：

```text
module:<file>:<start>:<end>
```

owner id 不包含 instance path、随机值或 elaborated parameter value。相同 source declaration 在
catalog 和 overlay 中必须得到同一 id。

### 5.3 排序与唯一性

- `modules` 按 `(declaration.file, declaration.start, declaration.end, name)` 排序；
- declaration range、owner id 各自全局唯一；
- module name 在一个 SourceSet 内存在多个物理定义时稳定失败，不按 compile order 任选其一；
- `top_closure_owner_ids` 按对应 ModuleOwner 的上述顺序排列；
- selected top 恰好一个；top closure 中允许包含 selected top 与 reachable child module；
- top-closure 文件中的同文件未实例化 module 必须保持 `in_top_closure=False`。

## 6. 固定 report schema

`to_report()` 返回：

```text
schema_version: 1
source_set:
  schema_version
  origin
  source_root
  ordered_source_files
  included_files
  include_dirs
  defines
  top
  top_closure_files
  compile_order
compile:
  catalog: {parse_errors: 0, semantic_errors: 0}
  top_overlay: null | {parse_errors: 0, semantic_errors: 0}
modules:
  - owner_id
    name
    declaration: {file, start, end}
    in_top_closure
    is_selected_top
top_closure_owner_ids
```

连续两次 `to_report()` 经 canonical JSON 序列化后必须 byte-identical。比较等价入口时，只允许
移除 `source_set.origin`；不能移除 modules、owner ids、ranges、closure 或 compile order。
`source_set` 必须等于 `source_set.to_report()` 的完整结果，不能另写第二套输入 report schema。

## 7. 稳定失败合同

| code | 条件 |
| --- | --- |
| `CATALOG_EMPTY_SOURCE_SET` | SourceSet 没有 `.sv` source unit |
| `CATALOG_PARSE_FAILED` | catalog 或 overlay 出现 parse error |
| `CATALOG_SEMANTIC_FAILED` | catalog 或 overlay 出现 semantic error |
| `CATALOG_DUPLICATE_MODULE` | 同名 module 有多个物理 declaration |
| `CATALOG_TOP_MISMATCH` | selected top 缺失、不是唯一 top instance，或 overlay owner 无法映射 |
| `CATALOG_RANGE_INVALID` | declaration range 越界、source bytes 不匹配、重复或重叠 |

异常字符串固定以 `"<code>: "` 开头。diagnostic 只记录首个稳定失败，不写 report 或缓存。
同名 module 检查必须在 semantic diagnostic 映射前执行，确保 duplicate fixture 稳定返回
`CATALOG_DUPLICATE_MODULE`，而不是依赖 PySlang 版本相关的 diagnostic code。

## 8. 固定 compact fixture

新增：

```text
tests/fixtures/refactor_source_catalog/
  design.f
  closure.f
  single.f
  rtl/child_bundle.sv
  rtl/top.sv
  rtl/unreachable.sv
  rtl/standalone.sv

tests/fixtures/refactor_source_catalog_invalid/
  duplicate.f
  rtl/first.sv
  rtl/second.sv
```

fixture 语义：

- `child_bundle.sv` 同时声明 reachable `child` 与未实例化 `colocated_unused`；
- `top.sv` 将 `child` 实例化两次，证明 repeated instance 不复制 owner；
- `unreachable.sv` 和 `standalone.sv` 不在 selected-top closure；
- `design.f` 按 `child_bundle.sv`、`top.sv`、`unreachable.sv`、`standalone.sv` 顺序列出；
- `closure.f` 只列 `child_bundle.sv`、`top.sv`；
- `single.f` 只列 `standalone.sv`；
- invalid fixture 的两个文件都声明 `module duplicate_name`。

所有 fixture 使用 `.sv` 和 SystemVerilog syntax；不增加 `.v` fixture。

## 9. 目标测试

新增 `tests/test_source_catalog.py`，至少覆盖：

1. 无 top 的 `design.f` catalog 包含 5 个物理 module owner，closure 为空；
2. `design.f + top` 仍 catalog 全部 5 个 module，但 closure 只有 `top` 和 `child`；
3. `child` 两次实例化只产生一个 owner；
4. `colocated_unused` 与 reachable module 同文件，但不进入 top closure；
5. project-root SourceSet 与 `closure.f + top` 的 normalized catalog report 除 origin 外相同；
6. single-file 与 `single.f` 的 normalized catalog report 除 origin 外相同；
7. 所有 owner id、declaration range、source bytes、排序和唯一性满足第 5 节；
8. canonical report 连续两次 byte-identical；
9. duplicate fixture 返回 `CATALOG_DUPLICATE_MODULE`；
10. monkeypatch 现有 inventory build/classification 入口为立即失败时，catalog 测试仍通过。

compact fixture 的 `5` 与 `2` 只用于验证本任务输入，不得进入产品分支或成为 RISC oracle。

## 10. 允许修改的文件

- `rtl_obfuscator/source_catalog.py`；
- `tests/fixtures/refactor_source_catalog/**`；
- `tests/fixtures/refactor_source_catalog_invalid/**`；
- `tests/test_source_catalog.py`；
- `docs/tasks/T040_source_catalog_owner_registry.md`，仅允许状态与子 Agent 执行记录。

禁止修改：

- `rtl_obfuscator/source_set.py` 和 T039 fixture/tests；
- `rtl_obfuscator/project.py`、`inventory.py`、`rewrite.py`；
- `encrypt.py`、mapping/decrypt/formal 脚本；
- README、renaming table、规划文档和历史任务；
- RISC-V-Vector 与 T038 fixture/tests。

## 11. 明确不包含

- 不收集任何可重命名 symbol、reference 或 occurrence；
- 不实现 SymbolGraph、RewritePolicy、mapping vNext 或 category selection；
- 不改写 RTL，不生成 gate，不解密，不计算 metrics；
- 不删除 legacy collector/test/script；
- 不为旧 mapping v1-v4 增加适配层；
- 不增加缓存、并行 compilation 或新依赖。

## 12. 子 Agent 强制流程

1. 完整阅读 `AGENTS.md`、本任务、总重构计划第 3/4/6 节和子 Agent 规范；
2. 确认 starting HEAD 为包含 T039 的提交，记录 `git status --short --branch`；
3. 将任务从 `READY` 改为 `IN_PROGRESS`，不得直接改为其他状态；
4. baseline 运行目标 unittest；预期因模块尚不存在而非零，并记录首个诊断；
5. 先新增 fixture 和测试，再实现最小 source catalog；
6. 每个可观察行为完成后只运行目标测试；
7. 遇到两个 PySlang view 无法通过 declaration range 映射、需要旧 inventory、或需要允许文件外
   修改时，记录后停止；
8. 完成后运行第 13 节四条命令；
9. 仅可设置 `READY_FOR_REVIEW`，填写第 14 节并停止；
10. 不执行 `git add`、commit、push，不创建下一任务。

子 Agent 禁止增加“主 Agent 验收记录”章节，禁止在任何字段声明任务 `ACCEPTED`。第 13 节状态
守卫失败时不得申请 review。

## 13. 唯一验收命令

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_source_catalog -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/source_catalog.py tests/test_source_catalog.py
git diff --check HEAD
rg -x -- '- 状态：`READY_FOR_REVIEW`' docs/tasks/T040_source_catalog_owner_registry.md
```

不运行全量 unittest、HDL compile、gate、decrypt、Yosys 或 RISC-V-Vector。原因是本任务只建立
semantic context 和 module source-owner registry，不产生 rewritten RTL。

## 14. 子 Agent 执行记录

```text
status: READY_FOR_REVIEW
starting_head: 7dc22d4446081126ab8c933fbd7eebd1f27269f3
changed_files: `rtl_obfuscator/source_catalog.py`; `tests/fixtures/refactor_source_catalog/**`; `tests/fixtures/refactor_source_catalog_invalid/**`; `tests/test_source_catalog.py`; this task record
commands: `conda run -n rtl_obfuscation python -m unittest tests.test_source_catalog -v`; `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/source_catalog.py tests/test_source_catalog.py`; `git diff --check HEAD`; `rg -x -- '- 状态：\`READY_FOR_REVIEW\`' docs/tasks/T040_source_catalog_owner_registry.md`
results: corrected overlay ordering so selected-top identity is validated immediately after parse checks and before generic semantic errors; added missing selected-top coverage. Unittest exit 0 with 11 tests passed; py_compile exit 0; `git diff --check HEAD` exit 0; READY_FOR_REVIEW status guard exit 0.
schema_or_behavior: implemented schema-v1 SourceCatalog, strict all-source catalog compilation, optional selected-top overlay, range-based shared ModuleOwner registry, repeated-instance deduplication, top closure flags, deterministic report serialization, stable duplicate/parse/semantic/top/range failures, and no-top behavior.
boundaries: catalog and overlay use the T039 SourceSet compile order, include dirs, defines, and separate PySlang views; selected-top identity is checked before generic overlay semantic errors; overlay closure recurses through every semantic module-instance container, including generate block arrays; no inventory/rewrite/mapping import or call, no RTL rewrite, no Formal, and no files outside the T040 allowlist were changed.
cleanup_candidates:
formal_verification: N/A - no rewritten RTL is produced
review_request: READY_FOR_REVIEW; selected-top mismatch coverage and all four section 13 commands passed. No commit, push, or next task was created.
```

## 15. READY_FOR_REVIEW 条件

- 第 9 节全部行为由目标测试覆盖；
- 第 13 节四条命令全部退出 `0`；
- 实际 diff 只包含第 10 节允许文件；
- catalog 与 overlay 共享 SourceSet、compile context 和 owner registry；
- repeated instance、同文件非闭包 module 和 closure 外 module 均按合同处理；
- 每个 owner range 的 source bytes 精确匹配；
- 没有导入或调用 inventory/rewrite/mapping；
- 任务状态严格为 `READY_FOR_REVIEW`；
- Formal 记录为 `N/A: no rewritten RTL is produced`。

## 16. 主 Agent 验收边界

主 Agent 将：

1. 审查 `HEAD → working tree` 完整 diff 和允许文件；
2. 独立运行第 13 节前 3 条命令，并在状态仍为 `READY_FOR_REVIEW` 时检查第 4 条；
3. 检查 normalized report、owner range/source bytes 和 top closure module identity；
4. 确认无 inventory/rewrite 调用；
5. 全部通过后才增加主 Agent 验收记录并设置 `ACCEPTED`。

主 Agent 验收前，子 Agent 产生的任何 `ACCEPTED` 文本均构成流程失败。

## 17. 主 Agent 验收记录

```text
status: ACCEPTED
reviewed_at: 2026-07-22
reviewed_head: 7dc22d4446081126ab8c933fbd7eebd1f27269f3
scope_review: PASS - working-tree changes are limited to the T040 allowlist
commands: `conda run -n rtl_obfuscation python -m unittest tests.test_source_catalog -v`; `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/source_catalog.py tests/test_source_catalog.py`; `git diff --check HEAD`; READY_FOR_REVIEW status guard before acceptance
results: PASS - 11 tests passed; py_compile exit 0; diff check exit 0; pre-acceptance status guard exit 0
direct_checks: PASS - generated top closure is exactly `child,top`; selected top is exactly `top`; missing selected top returns `CATALOG_TOP_MISMATCH`; source catalog has no inventory/rewrite/mapping dependency
formal_verification: N/A - no rewritten RTL is produced
decision: ACCEPTED
```
