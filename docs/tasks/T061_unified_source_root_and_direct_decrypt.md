# T061：统一 project-root 参数并直接解密

- 状态：ACCEPTED
- 合同版本：1.0
- 设计时间：2026-07-28
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T060 `ACCEPTED`
- 起始 HEAD：`008c9d3`
- 任务类型：公共 CLI 简化 + 无原始源码恢复

## 1. 单一目标

普通用户只通过同一个 `--source-root` 表达源码目录：

```sh
python rtl_encrypt.py \
  --source-root <项目目录> \
  --top <top module> \
  --output-dir <加密输出目录>
```

当公共加密命令没有 `--input`、没有 `--filelist`，但提供 `--source-root + --top` 时，
自动进入 project-root discovery。公共 CLI 不再显示或接受 `--project-root`。

公共解密只依赖 mapping 与加密 RTL：

```sh
python rtl_decrypt.py \
  --map <mapping.json> \
  --gate-dir <加密输出目录> \
  --output-dir <恢复输出目录>
```

用户无需提供原始 RTL，也无需理解或运行 Formal。Formal 继续由
`scripts/formal_equivalence.py` 独立负责。

## 2. 公共加密参数

只改变根目录 `rtl_encrypt.py` 的用户表面：

- single：
  `--input + --source-root + --output-dir`；
- filelist：
  `--filelist + --source-root + --output-dir`，`--top` 可选；
- project-root：
  `--source-root + --top + --output-dir`，不提供 `--input/--filelist`；
- public help 不出现 `--project-root`；
- public 传入 `--project-root` 必须由 argparse 拒绝，无 traceback、无输出；
- `--source-root` 没有 input/filelist 且缺少 top 时 fail-closed；
- T060 的默认 reports、category、top 自动跨 module、rate 行为保持不变。

内部兼容命令：

```text
python -m rtl_obfuscator.rewrite encrypt-vnext
```

继续保留原来的 `--project-root` 及其语义，不新增隐式 public project mode。

## 3. 公共直接解密

### 3.1 参数

公共 `rtl_decrypt.py`：

- `--map`：必填；
- `--gate-dir`：必填；
- `--output-dir`：必填；
- `--source-root`：不得出现在 public help，也不得接受；
- `--report`：可选；省略时只发布恢复后的 RTL，不生成恢复报告；
- 显式 `--report` 时保持与恢复目录一起原子发布；
- 缺参、路径冲突、篡改或发布失败均无 traceback、无部分输出。

内部兼容 `decrypt-vnext` 保持原有 `--source-root` 和 report 行为，历史测试不得迁移到
public 语义。

### 3.2 数据来源与验证

直接解密只能使用：

- orchestration mapping report；
- actual gate files；
- report 中的 effective mapping、per-file source/gate ranges；
- input/gate/restored manifests；
- 默认 metrics 或显式 reports。

实现必须复用 `restore_vnext.py` 已有 report/gate/range/manifest 审计，不得新增第二套
宽松 JSON parser。

恢复流程必须：

1. 校验 report schema、source-set 文件顺序和 gate 文件集合；
2. 校验 gate manifest 与 actual bytes；
3. 校验每个 rename 的 gate range 确实等于 renamed name；
4. 按 gate range 逆序替换为 original name；
5. 校验恢复后每个文件 SHA-256 与 input manifest 一致；
6. 对恢复后的临时源码执行既有 hydration/audit，确认 mapping、metrics、rate 和 summary
   仍一致；
7. 最后原子发布恢复目录和可选 report。

这里的 hydration 是产品完整性检查，不是 Formal；用户命令和 README 不得要求原始
source root 或 Formal。

### 3.3 API 边界

允许在 `restore_vnext.py` 抽取一个共享内部审计结果，使：

- `audit_orchestration_gate_vnext()` 保持既有公开行为；
- 新增 direct restore API，从 report + gate 生成 `RestoreVNext` 及恢复文件；
- 原有 `load_restore_vnext(... source_root=...)` 保持内部兼容。

不得复制 `_audit_gate_ranges`、manifest 解析或 mapping hydration。

## 4. README

继续保持 T060 面向数字 IC 工程师的章节与措辞，只做必要简化：

- 加密模式表中 project-root 的输入写成“源码根目录 + top module”；
- project-root 基础命令和示例用 `--source-root`，不再出现 `--project-root`；
- 说明：省略 input/filelist 并提供 source-root + top 时，工具自动扫描 top 使用的 RTL；
- 解密基础命令只显示 `--map`、`--gate-dir`、`--output-dir`；
- 不再要求或解释解密 `--source-root`；
- `--report` 只在常用可选参数中说明；
- 明确 Formal 验证是独立工具，不属于加密/解密基础命令；只用一句话链接
  `docs/formal_verification.md`，不介绍内部流程；
- 其他 T060 模式、rate、类型说明不得退化。

README 中禁止出现完整用户命令：

```text
python rtl_encrypt.py ... --project-root
python rtl_decrypt.py ... --source-root
```

## 5. 其他当前文档

- `docs/systemverilog_renaming_table.md` 保持用户型表格，只把模式说明与统一
  `--source-root + --top` 对齐；
- `docs/project_structure.md` 的 public decrypt 数据流改为 mapping + gate，不再写
  original source；
- `docs/formal_verification.md` 将当前用户 project 模式改为统一 source-root 入口，并明确
  Formal 是独立验证工具；
- 不改历史任务合同。

## 6. 黑盒验收

实际子进程必须覆盖：

1. public encrypt help 不含 `--project-root`，仍含 `--source-root`、`--top`；
2. public decrypt help 不含 `--source-root`，report 可选；
3. README 最简 project-root 命令
   `--source-root rtl_samples/example_fifo --top fifo_top --output-dir ...`
   成功，origin=`project-root`、19 categories、4 files、默认 reports；
4. public `--project-root` 非零、无 traceback、无输出；
5. source-root 没有 input/filelist/top 非零且无输出；
6. single/filelist 使用 source-root 的行为保持；
7. direct decrypt 无 source-root、无 report，4 files byte-identical，恢复目录只含源文件；
8. direct decrypt 显式 report 时恢复目录和 report 同时发布；
9. direct decrypt 使用 explicit map、default map、rate/no-rate 均通过；
10. mapping、metrics、gate bytes、gate file set、range 或 manifest 篡改均 fail-closed；
11. direct decrypt 不能接受 legacy v1-v4 mapping；
12. public decrypt 传 `--source-root` 被 argparse 拒绝；
13. 内部 encrypt-vnext 仍接受 `--project-root`；
14. 内部 decrypt-vnext 仍要求 source-root 并保持历史输出；
15. README 章节、命令和 Formal 独立工具说明受测试保护。

## 7. Formal

本任务改变 public project mode 路由，必须从 actual 隐式 project-root gate 执行：

```text
python rtl_encrypt.py \
  --source-root tests/fixtures/refactor_symbol_graph_parameters \
  --top parameter_top \
  --output-dir <actual-gate>
```

Formal：

```text
gold: tests/fixtures/refactor_symbol_graph_parameters/design.f
gate: actual-gate/design.f
top: parameter_top
seq: 5
positive: exit 0 and formal_equivalence=pass
negative: copy actual gate; exactly one inserted '~'; strict compile 0/0;
          Formal nonzero containing unproven and equiv_status -assert
```

不得运行 RISC-V-Vector Formal。

## 8. 允许修改

```text
rtl_obfuscator/rewrite.py
rtl_obfuscator/restore_vnext.py
tests/test_public_cli.py
tests/test_restore_vnext.py
tests/test_vnext_product_surface.py
README.md
docs/systemverilog_renaming_table.md
docs/project_structure.md
docs/formal_verification.md
docs/tasks/T061_unified_source_root_and_direct_decrypt.md
```

不允许修改 fixture、graph、policy、mapping、rate、Formal 脚本、历史任务合同或计划文档。

## 9. 子 Agent 验收

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_public_cli tests.test_restore_vnext tests.test_vnext_product_surface -v
```

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_cli_vnext_encryption tests.test_project_root_vnext -v
```

```sh
conda run -n rtl_obfuscation python -m py_compile \
  rtl_encrypt.py rtl_decrypt.py rtl_obfuscator/rewrite.py \
  rtl_obfuscator/restore_vnext.py tests/test_public_cli.py \
  tests/test_restore_vnext.py tests/test_vnext_product_surface.py
```

```sh
git diff --check HEAD
```

```sh
rg -x -- '- 状态：READY_FOR_REVIEW' \
  docs/tasks/T061_unified_source_root_and_direct_decrypt.md
```

## 10. 执行记录

- 状态变化：`READY -> IN_PROGRESS`。
- 实际起始 HEAD：`008c9d3ecc806eeb1e06c35ed9ae7f07ec024f45`。
- 实际起始分支：`main...origin/main [ahead 2]`。
- 实际起始工作区：

  ```text
  ?? docs/tasks/T061_unified_source_root_and_direct_decrypt.md
  ```

- 起始工作区只有主 Agent 新建的 T061 合同；没有其他未提交产品改动。
- 已完整读取 T061 合同、T060 合同与执行记录、`rewrite.py`、
  `restore_vnext.py`、当前 README、第 8 节允许测试及三份允许同步文档。
- 未执行 reset、checkout 或 clean。

### 10.1 实现与复用关系

- 状态变化：`IN_PROGRESS -> READY_FOR_REVIEW`。
- public encrypt parser 不再注册 `--project-root`。当 public namespace 没有 input/filelist，
  但存在 `--source-root + --top` 时，`_cli_vnext_validate_arguments()` 将其判定为项目模式，
  `_cli_vnext_source_set()` 继续调用唯一 `from_project_root()`。
- internal `encrypt-vnext` 仍注册并接受 `--project-root`；single/filelist 路由、默认
  category、top 自动跨 module 和 rate 流程继续复用 `_encrypt_vnext()`。
- public decrypt parser 不再注册 `--source-root`，`--report` 改为可选；internal
  `decrypt-vnext` 仍要求 `--source-root`，且保持省略 report 时由既有运行时门禁返回
  `RESTORE_VNEXT_OUTPUT_INVALID`。
- `restore_vnext.py` 将 `audit_orchestration_gate_vnext()` 的既有流程抽取为：
  - `_load_orchestration_gate_inputs_vnext()`：唯一 report/schema、gate file set、manifest
    chain、actual gate hash 和 range 审计；
  - `_audit_gate_ranges()`：在校验 renamed bytes、range coverage 和 overlap 后返回唯一
    反向替换集合；
  - `_materialize_direct_source_vnext()`：按 gate range 逆序恢复，并在写临时源码前校验
    SHA-256 与 input manifest 完全相同；
  - `_hydrate_orchestration_gate_vnext()`：用临时恢复源码调用既有
    `load_restore_vnext()`，重建 graph/policy/mapping、metrics、rate 和 summary；
  - `load_direct_restore_vnext()`：公开 direct restore API。
- 既有 `audit_orchestration_gate_vnext()` 和新增 direct API 共用以上四个步骤；没有复制
  JSON parser、manifest parser、range audit、mapping hydration 或 metrics 逻辑。
- public CLI 只将最终恢复目录和可选 report 交给既有 `publish_restore_vnext()` 原子发布。
  省略 report 时，恢复目录只包含 report 中列出的 RTL 源文件。

### 10.2 黑盒矩阵

- public encrypt help 包含 `--source-root`、`--top`，不包含 `--project-root`；
  public decrypt help 不包含 `--source-root`，显示 `[--report REPORT]`。
- public `--project-root`、缺 top 的 source-root 项目输入、public decrypt
  `--source-root` 均由 argparse/输入门禁拒绝，无 traceback、stdout 或输出目录。
- single 和 filelist 的 `--source-root` 行为保持；filelist + top 与隐式项目模式仍选择
  19 类并保持 top 对外边界。
- README FIFO 项目命令实际结果：
  - work-dir：`/tmp/t061-smoke.H0axPD`；
  - origin=`project-root`、top=`fifo_top`、4 files、81 mapping records、
    268 modified tokens；
  - strict compile、restore identity、coverage/leakage 门禁全部通过；
  - 默认 `mapping.json`、`metrics.json` 位于 gate。
- 不带 source-root/report 的 public decrypt 恢复 4 个文件；四次 `cmp` 均 exit 0，
  恢复目录只包含 `fifo_ctrl.sv`、`fifo_top.sv`、`fifo_storage.sv`、`fifo_if.sv`。
- 显式 report 时恢复目录和 report 同时发布，report 的
  `restored_input_manifest_equal=true`。
- direct restore 的 default/explicit map × rate/no-rate 四种组合全部通过，恢复文件均与
  fixture byte-identical。
- 篡改矩阵：

  | 篡改 | 结果 |
  | --- | --- |
  | orchestration mapping summary | `RESTORE_VNEXT_REPORT_INVALID` |
  | gate 内默认 metrics | `RESTORE_VNEXT_REPORT_INVALID` |
  | actual gate bytes | `RESTORE_VNEXT_GATE_INVALID` |
  | actual gate file set | `RESTORE_VNEXT_GATE_INVALID` |
  | effective mapping range | `RESTORE_VNEXT_REPORT_INVALID` |
  | execution input manifest | `RESTORE_VNEXT_REPORT_INVALID` |
  | legacy v4 mapping | `RESTORE_VNEXT_REPORT_INVALID` |

  所有失败均无 traceback、无恢复目录、无可选 report。
- 预先存在 report、输出与 gate 重叠、模拟 report 写入失败均保持已有目标不变且不留下部分
  输出。
- internal `encrypt-vnext --project-root` 和 internal
  `decrypt-vnext --source-root` 的历史测试继续通过。

### 10.3 验收命令

执行：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_public_cli tests.test_restore_vnext tests.test_vnext_product_surface -v
```

结果：26 tests，全部通过，exit code 0。

执行：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_cli_vnext_encryption tests.test_project_root_vnext -v
```

结果：10 tests，全部通过，exit code 0。

执行：

```sh
conda run -n rtl_obfuscation python -m py_compile \
  rtl_encrypt.py rtl_decrypt.py rtl_obfuscator/rewrite.py \
  rtl_obfuscator/restore_vnext.py tests/test_public_cli.py \
  tests/test_restore_vnext.py tests/test_vnext_product_surface.py
```

结果：exit code 0。

执行 `git diff --check HEAD`：exit code 0。

### 10.4 Formal

- actual work-dir：`/tmp/t061-formal.vL2qVG`。
- public gate 命令：

  ```sh
  conda run -n rtl_obfuscation python rtl_encrypt.py \
    --source-root tests/fixtures/refactor_symbol_graph_parameters \
    --top parameter_top \
    --output-dir /tmp/t061-formal.vL2qVG/gate
  ```

- actual summary：origin=`project-root`、top=`parameter_top`、3 files、
  27 mapping records、51 modified tokens、strict compile PASS、restore byte-identical。
- 正例命令：

  ```sh
  conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
    --gold-filelist tests/fixtures/refactor_symbol_graph_parameters/design.f \
    --gold-root tests/fixtures/refactor_symbol_graph_parameters \
    --gate-filelist /tmp/t061-formal.vL2qVG/gate/design.f \
    --gate-root /tmp/t061-formal.vL2qVG/gate \
    --top parameter_top --seq 5
  ```

  结果：exit code 0，`formal_equivalence=pass`。
- 负例从 actual gate 完整复制，只在 `rtl/child.sv` 一个 assignment 的 RHS 前插入一个
  `~`；tilde delta=1、byte delta=1。
- 负例 strict compile：catalog 0/0、top overlay 0/0。
- 负例运行同一 Formal 命令，仅将 gate 改为
  `/tmp/t061-formal.vL2qVG/negative`：exit code 1，包含 4 个 `unproven` 和
  `equiv_status -assert`。
- 未运行 RISC-V-Vector Formal。

### 10.5 文件、边界与 Git

- 修改仅限：

  ```text
  rtl_obfuscator/rewrite.py
  rtl_obfuscator/restore_vnext.py
  tests/test_public_cli.py
  tests/test_restore_vnext.py
  tests/test_vnext_product_surface.py
  README.md
  docs/systemverilog_renaming_table.md
  docs/project_structure.md
  docs/formal_verification.md
  docs/tasks/T061_unified_source_root_and_direct_decrypt.md
  ```

- 未修改 fixture、graph、policy、mapping、rate、Formal 脚本、历史合同或计划文档。
- direct decrypt 以 mapping 内嵌 metrics 为权威，并在 gate 内存在默认
  `metrics.json` 时额外校验其内容；显式写到 gate 外的独立 metrics 文件不是解密输入。
- 未执行 `git add`、commit 或 push，未设置 `ACCEPTED`，未创建 T062。
- 最终工作区为 `main...origin/main [ahead 2]`，包含上述 9 个 tracked 修改和一个未跟踪
  T061 合同。

## 11. 主 Agent 验收

主 Agent 必须独立复制 README 的 project-root 与 decrypt 基础命令，确认全程不提供
`--project-root` 或 decrypt `--source-root`，并检查：

- project discovery 与 T060 输出相同；
- mapping/metrics 默认位置不变；
- direct restore 只产生原始 RTL；
- 显式 report 可选；
- top 对外边界与子 module 改名保持；
- Formal 独立运行并通过正例/识别负例。

全部通过后才可设为 `ACCEPTED`。

### 11.1 独立验收结果

- 主 Agent 已审查全部允许文件；实现没有新增第二套 project discovery、mapping、restore
  或 Formal 流程。public project 模式仍调用唯一 `from_project_root()`，direct restore
  仍复用既有 report hydration，并在发布前完成 actual gate、range、manifest、metrics
  与 restored SHA-256 校验。
- 专项测试：26/26 通过。
- internal 兼容回归：10/10 通过。
- 显式排除 `tests.test_risc_v_vector_project_root` 的常规全量回归：190/190 通过。
- `py_compile`、`git diff --check HEAD`、`READY_FOR_REVIEW` 状态守卫均通过。
- README FIFO 命令在 `/tmp/t061-main-project.CBe6wM` 独立执行：
  - 仅使用 `--source-root rtl_samples/example_fifo --top fifo_top`；
  - origin=`project-root`、4 files、81 mapping records、268 modified tokens；
  - 默认 mapping/metrics、strict compile 和 restore identity 全部通过；
  - public decrypt 未提供 source-root 或 report，恢复目录只包含 4 个 RTL 文件，全部
    byte-identical。
- public encrypt help 不含 `--project-root`；public decrypt help 不含 `--source-root`，
  且 report 为可选参数。internal 两个 vNext 命令继续保留原参数行为。
- 主 Agent actual gate Formal 在 `/tmp/t061-main-formal.uvKFoX` 独立执行：
  - 3 files、27 mapping records、51 modified tokens；
  - 正例 exit 0，`formal_equivalence=pass`；
  - 负例仅插入一个 `~`，catalog/top-overlay strict compile 均为 0/0；
  - 负例 exit 1，包含 4 个 `unproven` 和 `equiv_status -assert`。
- 未运行 RISC-V-Vector Formal。
- 结论：T061 合同全部满足，状态由 `READY_FOR_REVIEW` 设为 `ACCEPTED`。
