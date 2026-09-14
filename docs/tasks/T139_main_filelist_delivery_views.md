# T139：main 原序 filelist 三视图与交付校验

- 状态：`ACCEPTED`
- 负责人：主 Agent（合同、冻结测试、独立验收与提交）/ Luna xhigh 子 Agent（实现与自测）
- 起始分支：`main`
- 起始提交：`7e6a1cb2186cba6d7cf778d8cb13ae24cfcb6bfb`
- 前置：T138 ACCEPTED，已推送 origin/main
- 验收类型：adapter 迁移，compact actual-gate / relocated export Formal 与固定功能负例

## 1. 单一目标

将 T136 `8173112` 的三视图交付及 T137 `e8b6b3a` 的最终原序路径替换行为迁入 main。
保留 T138 的统计/进度/运行记录和修正后的发布时序，不落地 T136 中间扁平化行为。
不引入 T130–T133 FAST 或 T134 `99d696e`；main 自有 T133 include 闭包直接保留。

必读 `AGENTS.md`、`docs/tasks/README.md`、`docs/development/process/refactor_subagent_protocol.md`、
`docs/formal_verification.md`。原 T136/T137 合同与实现通过 git show 读取，不整分支合并。

## 2. 冻结输入输出

主 Agent 冻结 `tests/test_t139_filelist_delivery.py`，子 Agent 不得修改。
它复用原 T137 的独立动态 fixture（不依赖 FAST），并增加两层嵌套/CRLF、export symlink、额外文件、
不完整视图、CLI-only context、两种非 filelist 输入模式与空白 include 负例。

公开显式 filelist 输入输出：

- `original_design.f`：与输入顶层文件逐字节一致，nested -f 保留原始引用，不作展开。
- `design.f`：以原文为模板，仅将物理路径和 nested 路径替换为最终 gate 绝对路径。
- `export_design.f`：同样原序原文，仅将路径替换为字面 `$OUT` 下的交付路径。
- 两套 reachable nested 镜像：`.rtl_obfuscation/filelists/design/...` 与 `.../export/...`。
- 注释、空行、换行（含 CRLF）、空白、`-v`、`-f`、define、多路径同一行 `+incdir+` 的顺序不变。
- CLI-only `--include-dir` / `--define` 不注入三视图；下游仍需另传，README 必须说明。
- include-only 物理依赖仍全部复制，但不添加为 compile entry；内部 strict gate 使用既有 canonical filelist。
- 单文件 / project-root 没有原始 filelist，使用 T136 的 canonical 三视图（include、define、compile_order）。
- SourceSet 当前不支持的 filelist 语法不扩展。`+incdir+` token 原值或环境展开后含空白必须明确拒绝，
  不引入引号、反斜杠解析或兼容 fallback。
- `--output-dir` 的最终绝对路径若含空白，应以 `CLI_VNEXT_OUTPUT_INVALID` 拒绝并不发布产物，
  因为其绝对路径必须写入不支持引号的 design.f。此限制只针对交付根；`--map`、`--metrics` 等
  不写入 filelist 的报告路径保留既有支持，不能因共用参数 helper 而一起收窄。

## 3. Restore / Formal 合同

1. public decrypt 接受完整三视图及可达 nested 闭包，拒绝缺少视图、额外/无引用文件、闭环、逃逸路径。
   design **和 export** 的 filelist 均必须是 gate 内普通物理文件；top/nested 文件或其路径组件不能用
   symlink 绕过 root 边界。原 FAST 测试只覆盖 design symlink，本任务新增 export 同等保护，不放宽任一视图。
2. SourceSet/Mapping schema 不变。保持原 RTL manifest、range、compile membership/order 与逐字节 restore 校验。
   不读取原始 nested filelist 来完成 public decrypt。允许 CLI-only context 的既有持久化元数据边界，
   不因不能重建原始空白而跳过 RTL 审计。
3. Formal parser 递归按原序处理 `-f`、`-v`、`+incdir+`、`+define+`、绝对路径及环境变量；
   gold 和 gate 上下文分别解析。保持 `equiv_status -assert` 和失败非零。
4. actual renamed gate/design.f 及复制后更换 OUT 的 export_design.f 均须 Formal pass；
   固定 XOR→OR 实际 gate 负例必须非零并含 unproven / equiv_status -assert。
5. 不声称移动后的绝对 design.f 仍有效。export 用于移动后编译/Formal；本任务不扩大 relocated decrypt 语义。

## 4. 不包含与允许文件

不改 FAST/FULL 引擎、no-top ABI、类别、rate 选择、名称/ranges、供应商归属、include discovery；
不改 `project_discovery.py` 或 main 原 T133 fixture；不进行 FULL/all 主流程提速，不跑 RISC/大型工程。
不删除历史测试。不恢复/覆盖 FAST task history，不 cherry-pick 整个提交。

子 Agent 只允许修改：

```text
rtl_obfuscator/source_set.py
rtl_obfuscator/rewrite.py
rtl_obfuscator/restore_vnext.py
scripts/formal_equivalence.py
README.md
docs/development/project_structure.md
docs/formal_verification.md
docs/tasks/T139_main_filelist_delivery_views.md
tests/test_t119_filelist_multi_root_output.py
tests/test_t133_include_physical_closure.py
tests/test_formal_equivalence.py
```

source_set.py 只迁移 path-view renderer/data 与歧义 include token 拒绝，不改已有闭包实现。
历史测试仅更新已改变的交付视图断言和 relocated negative 路径。
tests/test_formal_equivalence.py 原有已删除的 parameters/genvars/abi CLI 参数可依原 T136 改为 signals，
保留同一 fixture 的实际改名 gate 正例与固定功能负例；不声称恢复已删除 category 覆盖。
可迁入该测试的 root `+incdir+.` 交付/恢复/Formal 回归。

## 5. Baseline（唯一命令）

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t139_filelist_delivery -v
```

先更新 READY→IN_PROGRESS，记录起始 HEAD/主 Agent 新合同和冻结测试，再运行 baseline。
当前 main 无 export/original 三视图及 nested 镜像，相关测试预期失败；不得修改冻结测试让旧行为通过。

## 6. 固定验收（五条）

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t139_filelist_delivery -v

conda run -n rtl_obfuscation python -m unittest tests.test_t138_shared_run_observability tests.test_t119_filelist_multi_root_output tests.test_t133_include_physical_closure tests.test_formal_equivalence tests.test_public_cli tests.test_restore_vnext tests.test_source_set -v

conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/source_set.py rtl_obfuscator/rewrite.py rtl_obfuscator/restore_vnext.py scripts/formal_equivalence.py tests/test_t139_filelist_delivery.py tests/test_t119_filelist_multi_root_output.py tests/test_t133_include_physical_closure.py tests/test_formal_equivalence.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c 'from pathlib import Path; s=next(l for l in Path("docs/tasks/T139_main_filelist_delivery_views.md").read_text().splitlines() if l.startswith("- 状态：")); assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t139_ready_for_review=pass")'
```

命令 1 会调用 `scripts/formal_equivalence.py --gold-filelist <gate>/original_design.f --gold-root <project>
--gate-filelist <gate>/design.f --gate-root <gate> --top t139_top --seq 5`，并另跑 relocated export 正例/功能负例。
测试打印 `T139_FORMAL`：必须记录真实 gold/gate/top、exit 与 pass JSON。
主 Agent 在 READY_FOR_REVIEW 独立重跑同样五条命令后方可 ACCEPTED。

## 7. 执行记录（子 Agent）

- 开始：2026-09-14；分支 `main`；起始 HEAD `7e6a1cb2186cba6d7cf778d8cb13ae24cfcb6bfb`。
- baseline：`conda run -n rtl_obfuscation python -m unittest tests.test_t139_filelist_delivery -v`；起始结果
  13 tests，1 pass、5 failures、8 errors（缺少三视图/nested 镜像、canonical views、Formal filelist parser、空白
  `+incdir+` 拒绝均为预期缺口）。
- 目标实现后 T139：15 tests，15 pass；主 Agent 已将冻结 project-root 子用例的输出目录纠正为独立的
  尚不存在 `base/project-gate`，未放宽既有输出安全合同。
- 当前 changed_files：`README.md`、`docs/development/project_structure.md`、`docs/formal_verification.md`、
  `rtl_obfuscator/source_set.py`、`rtl_obfuscator/rewrite.py`、`rtl_obfuscator/restore_vnext.py`、
  `scripts/formal_equivalence.py`、`tests/test_formal_equivalence.py`、
  `tests/test_t119_filelist_multi_root_output.py`、`tests/test_t133_include_physical_closure.py`、本合同；
  冻结测试输入为 `tests/test_t139_filelist_delivery.py`（含主 Agent 的 project-gate 纠正及 output/report
  空白边界）。
- 已通过：T139 15 tests；T138/T119/T133/Formal/public CLI/restore/SourceSet 固定回归矩阵 34 tests；
  `py_compile` 指定文件；`git diff --check HEAD`。T139 实际 Formal：design gate exit 0 JSON
  `formal_equivalence=pass`、top `t139_top`、seq 5（本轮实际 gate
  `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-zl4zcud1/gate`，gold root
  `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-zl4zcud1/project`）；relocated
  export gate `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-zl4zcud1/relocated`
  的 `$OUT` view exit 0 同样 pass；实际 negative gate
  `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-zl4zcud1/negative` exit 1，
  诊断含 `unproven` 与 `equiv_status -assert`。
只可交付 READY_FOR_REVIEW，不接受、不提交、不推送、不创建下一任务。

## 8. 偏差或阻塞

2026-09-14 主 Agent 交付审查补充：绝对 design.f 无法表示含空白的 output-dir。
冻结 output-dir 空白拒绝及 custom map/metrics 空白路径保持可用的负/正例；不扩语法，不改报告路径能力。
main 的 include 宏参数 guard 属本任务禁止变更范围；测试和实现不得用 FAST fixtures 替代它。

2026-09-14 主 Agent 冻结用例纠正：non-filelist project-root 子用例原将 `base/project` 同时设为
已有源码目录与输出目录，产品按原有安全合同正确拒绝。主 Agent 将测试输出改为独立、尚不存在的
`base/project-gate`（single 同样使用 `base/single-gate`）。不放宽输出保护、不改变断言或产品语义。
子 Agent 应在此冻结测试修正后重跑完整五条验收，不得将修正前的目标失败记为通过。

## 9. 主 Agent 验收

2026-09-14 主 Agent 在 `READY_FOR_REVIEW` 状态、`main@7e6a1cb` 上独立重跑第 6 节全部五条命令：

1. T139 冻结黑盒测试：退出码 0，`Ran 15 tests in 1.777s`，`OK`。
2. T138/T119/T133/Formal/public CLI/restore/SourceSet 固定回归：退出码 0，
   `Ran 34 tests in 3.175s`，`OK`。
3. 指定文件 `py_compile`：退出码 0。
4. `git diff --check HEAD`：退出码 0。
5. 精确状态 guard：退出码 0，输出 `t139_ready_for_review=pass`。

命令 1 内部实际调用 `scripts/formal_equivalence.py`，公共参数为：

```text
--gold-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-d6t1ofdi/gate/original_design.f
--gold-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-d6t1ofdi/project
--top t139_top --seq 5
```

三次 gate 参数与结果：

```text
design 正例，exit 0：
--gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-d6t1ofdi/gate/design.f
--gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-d6t1ofdi/gate

relocated export 正例，exit 0：
OUT=/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-d6t1ofdi/relocated
--gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-d6t1ofdi/relocated/export_design.f
--gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-d6t1ofdi/relocated

实际 gate 的 rtl/top.sv 首个 XOR→OR 负例，exit 1：
OUT=/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-d6t1ofdi/negative
--gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-d6t1ofdi/negative/export_design.f
--gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-d6t1ofdi/negative
诊断包含 unproven 与 equiv_status -assert。
```

实际正例 JSON：

```json
{"formal_equivalence":"pass","gate":"/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-d6t1ofdi/gate","gold":"/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-d6t1ofdi/project","seq":5,"top":"t139_top"}
{"formal_equivalence":"pass","gate":"/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-d6t1ofdi/relocated","gold":"/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-d6t1ofdi/project","seq":5,"top":"t139_top"}
```

冻结用例同时确认 `modified_tokens > 0`，且实际 gate 字节不同于 gold；没有用 identity gate 替代证明。
测试临时目录由用例结束时自动清理，以上路径与结果为本次实测记录。

命令 2 独立复验 T138 的统计范围、完整交付/restore、quiet 持久化记录、发布完成时序与回滚，
其实际 gate Formal 为 pass，功能负例 exit 1。main 原 T133 的 literal include 闭包、
macro include 的 inventory 前拒绝、public roundtrip/Formal 正例和功能负例均通过。

范围审查：只修改第 4 节允许文件及主 Agent 冻结测试；`project_discovery.py`、
SourceCatalog、RenameIndex、mapping/range、rate 选择和 T138 orchestration 均无差异。
没有引入 FAST dispatch/引擎或 T134，没有改四组类别、no-top ABI 或供应商规则，未运行 RISC-V-Vector。
迁移范围内独立验收通过，由主 Agent 标记 `ACCEPTED`；不据此宣称 FULL/all 主流程性能得到解决。
