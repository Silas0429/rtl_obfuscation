# T132：修复多 declarator 声明列表

- 状态：`ACCEPTED`
- 负责人：子 Agent（实现与自测）/ 主 Agent（合同与验收）
- 起始分支：`delivery/fast-local-signals`
- 起始提交：`055f04c727ae8c669713c3b166cbfb1bb792e0c4`

## 1. 单一目标

修复 T131 definition-local signals 快速路径对 PySlang `SeparatedSyntaxList` 的错误假设：
`logic a, b;` / `wire c, d;` 的 `declarators` 会在两个 `DeclaratorSyntax` 之间返回逗号
`Token`。快速路径只能把真正的 `Declarator` 节点作为 signal candidate，不能把分隔符当作缺少名字的
声明而原子失败。

## 2. 固定输入

主 Agent 冻结以下输入，子 Agent 不得修改：

```text
tests/fixtures/t132_separated_declarator_list/design.f
tests/fixtures/t132_separated_declarator_list/formal.f
tests/fixtures/t132_separated_declarator_list/design.sv
```

公开复现命令：

```sh
python rtl_encrypt.py \
  --filelist tests/fixtures/t132_separated_declarator_list/design.f \
  --rewrite-root tests/fixtures/t132_separated_declarator_list \
  --category signals \
  --output-dir <new-output>
```

修复前固定失败：

```text
REFUSED_ATOMIC: direct signal declarator has no name
```

## 3. 冻结行为

1. `_direct_signal_declarations` 迭代 PySlang separated declarator list 时，只处理 CST kind 精确为
   `Declarator` 的节点；逗号等 separator token 不是 candidate，必须跳过。
2. 不得改成字符串拆分、正则声明解析、semantic lookup、fallback 或按 fixture/模块名特判。
3. 每个真实 declarator 仍必须具有非空名字、可信物理 source range，并满足 T131 的直接
   module-local `logic/wire` 边界；真实 `Declarator` 缺名仍然 fail-closed。
4. T132 fixture 中 `first`、`second`、`third`、`fourth`、`fifth`、`folded` 六个对象必须各产生
   一个 `signals` record，全部 `action=rename`；comma token 不得产生 record。
5. CLI、SourceSet、MappingVNext、report、rewrite、restore、strict gate compile 和 T131 的
   `syntax_local_ambiguous` 规则全部不变。

## 4. 不包含

- 不增加新的可加密声明类型，不支持 ports/parameters/typedef/interface/struct/function locals。
- 不恢复 PySlang semantic `Compilation`、top、instance hierarchy、dependency closure 或 per-module elaborate。
- 不修改 vendor 精确放行、filelist 解析、命名策略、mapping schema 或用户参数。
- 不顺手重构 T131 索引，不运行 RISC-V-Vector Formal，不运行真实 StCache/AICluster。

## 5. 允许修改文件

```text
docs/tasks/T132_separated_declarator_list.md
rtl_obfuscator/fast_local_signals.py
tests/test_t132_separated_declarator_list.py
```

第 2 节 fixture 是主 Agent 冻结输入。需要修改其他文件时必须记录偏差并停止。

## 6. 预期机器可读结果

```text
CLI exit                         = 0
format                           = rtl-obfuscation.cli-vnext
schema_version                   = 2
summary.strict_compile_passed    = true
summary.restored_byte_identical  = true
mapping records                  = 6 rename / 0 preserve / 0 unsupported
decrypt design.sv                = byte-identical
actual rewritten gate Formal     = pass
fixed functional negative Formal = fail
```

## 7. Baseline

子 Agent 修改实现前必须运行：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t132_separated_declarator_list.T132SeparatedDeclaratorListTests.test_public_multideclarator_roundtrip -v
```

预期失败且包含 `direct signal declarator has no name`。

## 8. 固定验收命令

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t132_separated_declarator_list -v

conda run -n rtl_obfuscation python -m unittest \
  tests.test_t131_definition_local_signals \
  tests.test_t130_fast_local_signals -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/fast_local_signals.py \
  tests/test_t132_separated_declarator_list.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c 'from pathlib import Path; s=next(l for l in Path("docs/tasks/T132_separated_declarator_list.md").read_text().splitlines() if l.startswith("- 状态：")); assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t132_ready_for_review=pass")'
```

第一条必须运行公开 CLI、strict gate、decrypt byte identity，以及实际 rewritten gate 的 Formal 正例和
固定功能负例：

```text
gold-filelist = tests/fixtures/t132_separated_declarator_list/formal.f
gold-root     = tests/fixtures/t132_separated_declarator_list
gate-filelist = <actual gate>/formal.f
gate-root     = <actual gate>
top           = t132_multi_declarators
seq           = 5
positive      = exit 0 and JSON formal_equivalence=pass
negative      = actual gate 中唯一 ` ^ 4'h3` 改为 ` | 4'h3`，exit nonzero，含 unproven 与 equiv_status -assert
```

## 9. 子 Agent 执行记录

```text
status: READY_FOR_REVIEW
starting_head: 055f04c727ae8c669713c3b166cbfb1bb792e0c4
started_at: 2026-09-02 +0800
changed_files: docs/tasks/T132_separated_declarator_list.md, rtl_obfuscator/fast_local_signals.py, tests/test_t132_separated_declarator_list.py
commands: >-
  baseline: conda run -n rtl_obfuscation python -m unittest tests.test_t132_separated_declarator_list.T132SeparatedDeclaratorListTests.test_public_multideclarator_roundtrip -v;
  targeted rerun: same command after Declarator filter and corrected fixture;
  acceptance: all five commands in Section 8
results: >-
  baseline exit 1 with REFUSED_ATOMIC direct signal declarator has no name;
  targeted exit 0; T132 module 2 tests exit 0; T130/T131 14 tests exit 0;
  py_compile exit 0; git diff --check HEAD exit 0; ready guard t132_ready_for_review=pass
schema_or_behavior: >-
  exact Declarator CST nodes are candidates and separator Tokens are skipped;
  six records are rename, zero preserve/unsupported; CLI schema 2, strict compile and restore identity pass
boundaries: T131 occurrence rules unchanged; no new declaration categories, fallback, semantic Compilation, or hierarchy
cleanup_candidates: none
formal_verification: >-
  PASS. gold-filelist=tests/fixtures/t132_separated_declarator_list/formal.f;
  gold-root=tests/fixtures/t132_separated_declarator_list; gate-filelist=/tmp/t132-evidence.QkUx5h/gate/formal.f;
  gate-root=/tmp/t132-evidence.QkUx5h/gate; top=t132_multi_declarators; seq=5;
  positive command exit 0 with {"formal_equivalence":"pass","top":"t132_multi_declarators","seq":5};
  fixed negative changed the sole " ^ 4'h3" to " | 4'h3", exit 1 with unproven and equiv_status -assert
review_request: READY_FOR_REVIEW; awaiting Main Agent independent acceptance; no commit/push
```

## 10. 偏差或阻塞

```text
初始冻结输入曾把既有 IdentifierSelectName 数组下标边界混入 separator 单目标；该问题已由主 Agent
按合同修正输入解决。实现未扩展 occurrence 规则，当前无剩余偏差或阻塞。

contract_correction_2026-09-02: "主 Agent 冻结输入误把既有 IdentifierSelectName 数组下标边界混入
separator 单目标。为保持 T132 不扩展 occurrence 规则，主 Agent 将 arrayed 改为普通直接 logic fifth；
多 declarator、net initializer 与固定 Formal 变异仍保留。子 Agent 不承担该 fixture 修正。"
```

## 11. 主 Agent 验收记录

```text
status: ACCEPTED
reviewed_head: 055f04c727ae8c669713c3b166cbfb1bb792e0c4 + T132 working tree
acceptance: "主 Agent 独立执行第 8 节五条命令：T132 2/2；T131/T130 14/14；py_compile pass；git diff --check HEAD pass；READY_FOR_REVIEW guard pass。"
code_review: "产品代码仅增加 exact Declarator kind 过滤；PySlang SeparatedSyntaxList 中 comma Token 被跳过，真实 Declarator 仍执行原有非空 name、物理 range、module-local logic/wire 及 occurrence 安全检查。未修改 T131 occurrence allowlist、候选类别、Compilation/top/hierarchy、CLI 或 schema。"
blocking_findings: "none；主 Agent 初始 fixture 混入 IdentifierSelectName 数组边界，已通过合同输入勘误移除，没有转化为实现扩展。"
resolution: "ACCEPTED；服务器同源错误的最小修复完成。"
formal_verification: "PASS；主 Agent 固定第一条验收独立运行实际 rewritten gate Formal。gold tests/fixtures/t132_separated_declarator_list/formal.f，gate 为公开 CLI 生成的实际加密 design.sv/formal.f，top t132_multi_declarators，seq 5；正例 exit 0 且 formal_equivalence=pass；固定 ^ 4'h3 -> | 4'h3 负例 exit nonzero，含 unproven 与 equiv_status -assert。"
next_step: "提交并推送 delivery/fast-local-signals；服务器更新后用新的空 OUT 重跑 StCache。"
```
