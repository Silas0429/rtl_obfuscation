# T099：统一 filelist 编译上下文

- 状态：`ACCEPTED`
- 设计负责人：主 Agent
- 实现负责人：GPT-5.6 Luna Extra high 子 Agent
- 前置任务：T098；当前基线 `9eaae53`
- 任务类型：adapter 迁移
- 执行规范：[`refactor_subagent_protocol.md`](../development/process/refactor_subagent_protocol.md)
- Formal verification：必须使用本任务 compact filelist 的 actual renamed gate 正例和固定功能负例

## 1. 单一目标

把显式 filelist 中直接列出的 `.h/.svh/.vh` 统一为同一种全局预处理上下文，并让 SourceSet、
SourceCatalog、strict gate、restore、canonical `design.f` 和 Formal 使用唯一有效编译顺序；同时把
PySlang `MissingTimeScale` 明确分类为不影响标识符绑定的非阻塞环境诊断，其他 parse/semantic error
继续严格失败。

```text
expanded explicit filelist
  -> explicit header prelude (.h/.svh/.vh, first occurrence order)
  -> listed source units (.sv/.v, original source order)
  -> one effective compile_order
  -> shared PySlang / gate design.f / restore / Formal
```

本任务替换 T098 的 `.h`-only prelude 和 source-only `compile_order`。不得保留双轨 helper、旧
source-only design.f 分支或按后缀选择不同 parser 的兼容层。

## 2. 冻结数据合同

### 2.1 唯一有效编译顺序

显式 filelist 展开环境变量和嵌套 `-f` 后：

- `ordered_source_files` 只包含 `.sv/.v`，严格保持 source 首次出现顺序；这些文件是 module catalog
  和 rename target；
- `included_files` 包含显式和 include closure 的 `.h/.svh/.vh` 物理文件；不得成为 rename target；
- `compile_order` 对 filelist 模式固定为：

```text
explicit .h/.svh/.vh in first occurrence order
+ ordered_source_files
```

- include closure 中仅由 `` `include`` 发现、未直接列入 filelist 的 header 不进入 `compile_order`；
- `compile_order` 可以与 `included_files` 重叠，但它的 source 投影必须精确等于
  `ordered_source_files`，header 投影必须全部属于显式 header；任何重复或未登记物理文件都失败；
- single-file 与 project-root 的 `compile_order` 继续只含其 source units；project-root discovery 不变；
- generated gate 与 formal view 的 canonical `design.f` 必须逐行精确写入 `compile_order`，不再写
  source-only 旧格式；
- mapping/restore schema version 保持当前 vNext schema 1，不新增第二套 schema、reader 或 fallback。

### 2.2 一个 PySlang helper

- `compile_pyslang_source_set()` 删除 `source_files + context_files` 的分离输入，改为唯一
  `compilation_files`（或等价单序列命名）；不得保留旧参数兼容；
- `SyntaxTree.fromFiles()` 按 `compilation_files` 原样执行；显式 header prelude 先定义宏，source
  后解析；
- authoritative filelist SourceSet validation 与 `SourceCatalog._compile_view()` 都传同一
  `compile_order/include_dirs/defines/top`；
- source catalog 仍只从 `ordered_source_files` 建 module owner，header 不产生 rename symbol；
- top closure 仍只返回 reachable `.sv/.v`，不得把 header 冒充 module source；
- 不得恢复 `_ProjectContext` macro/type/module provider discovery，不得新增宏名或类型名白名单。

### 2.3 `MissingTimeScale` 边界

- shared PySlang result 必须保留 raw error diagnostics，并显式拆分：
  `parse_errors`、`semantic_errors`、`nonblocking_errors`；
- 只有精确的 `DiagCode(MissingTimeScale)` 可以进入 `nonblocking_errors`；它不得计入 SourceSet 或
  SourceCatalog blocking error 数；
- 原因固定为：本产品只改名并原样保留 RTL time declarations；缺失 simulator default timescale
  不影响 symbol binding、source range 或 rewrite bytes；本任务不猜测 `1ns/1ps`，也不改变 RTL；
- `UnknownDirective`、`ExpectedExpression`、`UnknownModule` 以及其他全部 error 仍 fail-closed；
- 若同时有 parse 与 semantic error，parse failure 的 `details` 只能包含 blocking parse errors；修复
  parse 后才报告 blocking semantic errors，不再把 `MissingTimeScale` 排到“parse errors”首项；
- 不增加通用 ignore list、命令行 suppress 开关或 simulator 配置兼容层。

## 3. 输出、发布和恢复

- generated gate 必须复制全部 physical files；header bytes 保持不变且无 mapping record；
- gate `design.f`、formal view `design.f` 和 persisted SourceSet `compile_order` 三者字节一致；
- strict gate 使用同一 effective compile order 和同一诊断分类；不得仅在 gold 放宽；
- decrypt 必须验证新的 canonical `design.f`，并恢复全部 source/header byte-identical；
- Formal gold/gate 两侧必须使用各自 effective `design.f`，不能复制 gold、删除 header 或改回
  source-only list；
- 输入失败或 strict gate 失败时仍保持原子发布，不创建部分 output/mapping/metrics。

## 4. Compact fixture 与机器可验收结果

新增 `tests/fixtures/t099_filelist_compile_context/`：

- filelist 故意先列 source、后列显式 `.h` 和 `.svh`；
- `.h` 控制 `.svh` 中的条件宏，source 不使用 `` `include`` 而直接使用 `.svh` 定义；
- source 顺序故意非路径排序，并包含 selected top、child 和一个 closure 外合法 source；
- 后置 source 含 `` `timescale``，使原始 PySlang raw diagnostics 稳定产生
  `MissingTimeScale`；
- 一个负例移除显式宏 header，稳定产生 blocking parse error；
- 一个负例移除 child，稳定产生 blocking semantic error，同时可能存在 `MissingTimeScale`。

`tests/test_t099_filelist_compile_context.py` 必须验证：

1. `ordered_source_files` 保持 source 顺序；`included_files` 包含两个显式 header；
   `compile_order` 精确等于 header prelude + source 顺序；top closure 只含 reachable source；
2. raw shared compile result 只把 `MissingTimeScale` 放入 `nonblocking_errors`，SourceSet 与
   SourceCatalog 成功且 catalog/top overlay blocking errors 为 0；
3. 缺 header 返回 `SOURCESET_DISCOVERY_FAILED`、message 为 filelist PySlang parse failure，details
   不包含 `MissingTimeScale`；缺 child 返回 semantic failure，且两者均不发布输出；
4. public `signals` 加密成功，gate `design.f` 与 effective `compile_order` 字节一致，header 无 edit，
   strict compile 通过，decrypt 全部物理文件 byte-identical；
5. actual renamed gate Formal exit 0 且 JSON `formal_equivalence=pass`；从 actual gate 复制的固定功能
   负例仍用同一 header/context order、strict compile 为 0 errors，Formal 非零且包含 `unproven` 和
   `equiv_status -assert`；
6. 受本合同替换的 T088/T090/T091/T095/T098 断言迁移到唯一 `compile_order`；不得删除测试 method
   或保留 source-only design.f 兼容断言。

## 5. 明确不包含

- 不修改服务器 ChipPlatform、StCache filelist 或真实 RTL；
- 不支持 vendor `-y/-v/+libext`、library map、shell、glob、blackbox 或 generated source；
- 不增加 `--timescale`、`+timescale`、diagnostic suppress、兼容 schema 或 legacy reader；
- 不改变 19 category、SymbolGraph、RewritePolicy、MappingVNext record、rate 或 public 三模式参数矩阵；
- 不删除 project-root discovery；不运行 RISC-V-Vector Formal 或 blanket unittest discovery；
- 不修改旧 RTL fixture；所有新语义形状只放在 T099 fixture；
- 不以 `defaultTimeScale` 猜值掩盖输入，也不忽略除 `MissingTimeScale` 之外的 PySlang error。

## 6. 允许修改

```text
README.md
docs/development/project_structure.md
docs/formal_verification.md
docs/tasks/T099_filelist_compile_context.md
rtl_obfuscator/project_discovery.py
rtl_obfuscator/source_set.py
rtl_obfuscator/source_catalog.py
rtl_obfuscator/rewrite_vnext.py
rtl_obfuscator/restore_vnext.py
rtl_obfuscator/formal_vnext.py
tests/test_t099_filelist_compile_context.py
tests/fixtures/t099_filelist_compile_context/**
tests/test_source_set.py
tests/test_t088_verilog_suffix.py
tests/test_t090_filelist_context.py
tests/test_t091_h_macro_header.py
tests/test_t095_macro_formal_parameters.py
tests/test_t098_authoritative_filelist.py
```

实现必须直接替换旧 helper/validation 分支；不得新建 adapter、compat、legacy 或 migration 模块。
允许列表外不得修改；子 Agent 不得 commit、push 或设置 `ACCEPTED`。

## 7. 固定验收命令

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t099_filelist_compile_context tests.test_source_set \
  tests.test_t088_verilog_suffix.VerilogSuffixTests.test_filelist_preserves_mixed_sv_v_order_and_header_classification \
  tests.test_t088_verilog_suffix.VerilogSuffixTests.test_include_escape_is_stable_and_does_not_publish \
  tests.test_t088_verilog_suffix.VerilogSuffixTests.test_invalid_suffixes_fail_closed_without_publishing_gate \
  tests.test_t088_verilog_suffix.VerilogSuffixTests.test_public_help_names_both_source_suffixes \
  tests.test_t088_verilog_suffix.VerilogSuffixTests.test_public_three_modes_preserve_suffixes_and_header_is_actually_rewritten \
  tests.test_t088_verilog_suffix.VerilogSuffixTests.test_sourceset_accepts_mixed_v_and_vh_across_three_entries \
  tests.test_t090_filelist_context \
  tests.test_t091_h_macro_header.HMacroHeaderTests.test_filelist_h_is_context_only_and_macro_provider_is_resolved \
  tests.test_t091_h_macro_header.HMacroHeaderTests.test_public_signals_gate_restore_and_h_bytes \
  tests.test_t095_macro_formal_parameters tests.test_t098_authoritative_filelist -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/project_discovery.py rtl_obfuscator/source_set.py rtl_obfuscator/source_catalog.py \
  rtl_obfuscator/rewrite_vnext.py rtl_obfuscator/restore_vnext.py rtl_obfuscator/formal_vnext.py \
  tests/test_t099_filelist_compile_context.py tests/test_source_set.py \
  tests/test_t088_verilog_suffix.py tests/test_t090_filelist_context.py \
  tests/test_t091_h_macro_header.py tests/test_t095_macro_formal_parameters.py \
  tests/test_t098_authoritative_filelist.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c \
  'from pathlib import Path; text=Path("docs/tasks/T099_filelist_compile_context.md").read_text(encoding="utf-8"); assert "- 状态：`READY_FOR_REVIEW`" in text; print("READY_FOR_REVIEW guard=pass")'
```

第一条中的 T099 actual-gate 测试是本任务唯一 Formal 正负证据；不得另外运行历史 Formal 或 RISC。

## 8. 执行记录

```text
status: READY_FOR_REVIEW
starting_head: 9eaae530006b42a8c5c90ad24dc94e455c70090f
changed_files: README.md; docs/development/project_structure.md; docs/formal_verification.md; docs/tasks/T099_filelist_compile_context.md; rtl_obfuscator/project_discovery.py; rtl_obfuscator/restore_vnext.py; rtl_obfuscator/rewrite_vnext.py; rtl_obfuscator/source_catalog.py; rtl_obfuscator/source_set.py; tests/test_source_set.py; tests/test_t088_verilog_suffix.py; tests/test_t090_filelist_context.py; tests/test_t091_h_macro_header.py; tests/test_t095_macro_formal_parameters.py; tests/test_t098_authoritative_filelist.py; tests/test_t099_filelist_compile_context.py; tests/fixtures/t099_filelist_compile_context/**
commands: baseline fixed unittest (T099 module absent, 33 existing tests passed, exit 1); review correction fixed unittest (37 tests, exit 0); fixed py_compile (exit 0); git diff --check HEAD (exit 0); READY_FOR_REVIEW guard (exit 0)
results: T099 order/context, package/interface top closure, parse-vs-semantic fail-closed behavior, MissingTimeScale classification, gate/restore, missing_header and missing_child public no-publish assertions, and regression assertions all passed; missing_child public CLI returned nonzero with empty stdout, semantic failure detail, and no output; negative SourceSet+SourceCatalog strict compile preserved canonical order with catalog/top overlay parse_errors=0 and semantic_errors=0; no provider discovery call, no partial output on input failure
schema_or_behavior: filelist compile_order is explicit .h/.svh/.vh first-occurrence prelude plus listed .sv/.v source order; SourceSet and SourceCatalog share compilation_files; only DiagCode(MissingTimeScale) is nonblocking; all other PySlang errors remain blocking; project-root and single-file compile_order behavior is unchanged
boundaries: sections 2, 3 and 5
cleanup_candidates: source-only filelist compile_order assertions are replaced in place; no compatibility layer is retained
formal_verification: PASS; T099 actual gate positive used gold=<temporary>/gold/design.f (canonical header-prelude + source order), gate=<temporary>/gate/design.f, top=t099_top, command `python scripts/formal_equivalence.py --gold-filelist <gold>/design.f --gold-root <gold> --gate-filelist <gate>/design.f --gate-root <gate> --top t099_top --seq 5`, exit 0, JSON formal_equivalence=pass/top=t099_top/seq=5; fixed functional negative used copied actual gate with `assign out_y = 1'b0;`, first passed project SourceSet+SourceCatalog strict compile with the same canonical order and zero catalog/top overlay parse/semantic errors, supplemental Icarus exit 0, Formal exit 1 with `unproven` and `equiv_status -assert`
review_correction: Main Agent first review returned three in-contract corrections: add missing_child public no-publish coverage; make T099 fixture prove package/interface reachable closure; make functional negative run project SourceSet+SourceCatalog strict compile before Formal.
acceptance_matrix_correction: Main Agent found that the first frozen command named the whole T088 module and therefore ran its historical Formal in addition to T099; the command now enumerates T088's six non-Formal methods so T099 remains the sole Formal evidence, without changing implementation scope or product behavior.
review_request: READY_FOR_REVIEW after in-contract review correction; no commit, push, or ACCEPTED status set
```

## 9. 主 Agent 验收

```text
acceptance_status: ACCEPTED
acceptance_head: 9eaae530006b42a8c5c90ad24dc94e455c70090f
allowed_files: PASS; all modified and added paths are listed in section 6, no old fixture or out-of-scope module changed
independent_commands: corrected four fixed commands in section 7; retained-path T099 public encryption; retained-path project SourceSet+SourceCatalog strict negative compile; retained-path scripts/formal_equivalence.py positive and fixed functional negative
independent_results: corrected unittest exit 0, Ran 36 tests in 1.899s, OK; py_compile exit 0; git diff --check HEAD exit 0; READY_FOR_REVIEW guard exit 0; public encryption exit 0 with rename=3, preserve=8, unsupported=5, strict_compile_passed=true and restored_byte_identical=true
formal_verification: PASS; gold `/tmp/rtl_obfuscation_t099_main.EYPasv/gold`, actual gate `/tmp/rtl_obfuscation_t099_main.EYPasv/gate`, top `t099_top`; positive command `conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist /tmp/rtl_obfuscation_t099_main.EYPasv/gold/design.f --gold-root /tmp/rtl_obfuscation_t099_main.EYPasv/gold --gate-filelist /tmp/rtl_obfuscation_t099_main.EYPasv/gate/design.f --gate-root /tmp/rtl_obfuscation_t099_main.EYPasv/gate --top t099_top --seq 5`, exit 0, JSON `{"formal_equivalence":"pass","gate":"/tmp/rtl_obfuscation_t099_main.EYPasv/gate","gold":"/tmp/rtl_obfuscation_t099_main.EYPasv/gold","seq":5,"top":"t099_top"}`; fixed functional negative `/tmp/rtl_obfuscation_t099_main.EYPasv/negative` first passed project SourceSet+SourceCatalog with canonical header-prelude compile_order and catalog/top overlay parse/semantic errors 0/0, then the same Formal command with negative gate exited 1 and reported one `unproven` cell plus `equiv_status -assert`
decision: ACCEPTED; explicit .h/.svh/.vh now use one header prelude, every vNext stage and canonical design.f use one compile_order, MissingTimeScale alone is nonblocking, and all other PySlang errors remain fail-closed without compatibility layers
```
