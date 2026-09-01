# T123：真实 filelist 资源与库语义诊断记录

- 状态：`ACCEPTED`
- 记录日期：`2026-09-01`
- 主 Agent：Codex
- 基线 HEAD：`d1c43d7ac8d00687eb6974654f78f4cce6c10338`（`main`、`origin/main`、`gitlab/main` 同步）
- 记录类型：服务器实测快照 / 后续方案讨论输入
- 实现授权：无；本记录不授权修改产品代码、测试、CLI 或 schema
- 记录验收：主 Agent 已按用户要求完成现状固化；`ACCEPTED` 只表示诊断快照已记录，不表示其中候选方案已批准

## 1. 当前结论

项目已经解决真实 filelist 进入流程前的若干输入兼容问题，但完整工程目前仍不能完成一次加密运行。
最新服务器运行不再被 20 GiB 登录会话限制直接杀死，而是在约 599 GiB 峰值内存后，因同名 module
存在两份物理声明而原子失败。

当前问题不是简单的“给 PySlang 更多内存就能完成”，也不能归结为一个已经证实的 PySlang 内存泄漏。
现有证据支持以下分层判断：

1. 完整输入本身很大，PySlang 对全部 source unit 建立语法树、语义树并 elaborate，约 20 GiB 是已观测到的
   第一层基础成本。
2. 项目把 `-v` 文件转换成普通 source entry，丢失了“按需库文件”的来源语义；随后又先执行一次
   `top=None` 的全库 catalog 编译。这会让大量本不应同时 elaborate 的标准单元、存储器模型和重复库副本
   一起进入语义模型，是约 599 GiB 峰值的主要可疑放大路径。
3. 项目还会把完整 PySlang semantic/CST 节点收集进 Python list，并在后续阶段保留 Compilation，继续进行
   top overlay、RenameIndex 和 gate compilation。这些用法进一步放大峰值，但最新失败发生在第二次 top
   overlay 之前，因此尚未走到最坏的完整流水线峰值。
4. T122 修复的“每条兼容诊断读取整个物理文件”确实是不合理实现，但服务器复测峰值仍约 20 GiB，说明它
   不是此前 SIGKILL 的主要内存来源。

因此，后续讨论必须同时处理“分析范围 / 对象生命周期”和“真实 `-v` 库语义 / 重复定义选择”，不能只做
内存参数调整，也不能简单跳过 rewrite root 外的所有文件。

## 2. 当前仓库状态

```text
branch: main
head: d1c43d7 [FIX] Bound vendor diagnostic source reads
remote: main == origin/main == gitlab/main
working_tree_before_this_record: clean
active_implementation_task: none
```

最近三个相关任务均已验收：

- T120：支持 filelist 显式 `.vic` 参数上下文及后续 include 引用；
- T121：精确放行已确认的供应商诊断，并把命中这些诊断的物理文件设为只读；
- T122：供应商诊断物理字节核验改为最多 4096-byte 的有界流式读取。

当前实现边界仍然是：

- `.v` 与 `.sv` 都是 SystemVerilog semantic frontend 的 source unit；后缀不选择另一套 parser；
- `-v path` 已能被 filelist parser 接受，但目前会被标准化为与裸路径相同的 source entry；
- `-v` 不等于只读，也不决定能否加密；
- 尚未实现真实 simulator 的 lazy library search、`-y`、`+libext`、库顺序优先级或重复 definition 选择；
- `--rewrite-root` 只控制改写资格，不缩小 PySlang 的 compile order；
- 命中 T121 精确供应商诊断的文件只读，但没有这些诊断的目录外文件或嵌套供应商副本不会因此自动只读。

## 3. 已解决的真实输入阻塞

服务器输入曾依次暴露以下问题，当前仓库均已有对应修复：

1. filelist 中的 `-v /absolute/path/file.v` 无法解析：T117 已支持语法输入，但只实现了裸 source 等价语义；
2. filelist 根被推断为 `/`，导致输出目录误判与 source root 重叠：T119 已处理多根 filelist 的输出保护；
3. `dmac_parameters_64bit.vic` 被拒绝：T120 已支持显式 `.vic` context 及 include 约束；
4. 供应商模型中的 `` `protect``、`` `endprotect``、`` `suppress_faults``、
   `` `enable_portfaults``、`` `disable_portfaults``、`` `nosuppress_faults`` 以及特定 `ifnone` 诊断阻塞：
   T121 已精确放行，其他未知 directive 仍 fail closed；
5. 每条放行诊断都会整文件读取：T122 已改为固定上限的流式物理字节核验。

T121 当前精确边界为：

```text
IfNoneEdgeSensitive: 384
UnknownDirective:    128
total observed:      512
```

这不是通用供应商语法兼容层；只有物理源字节与已冻结形状精确匹配时才放行。

## 4. 真实 filelist 规模

此前服务器审计记录：

```text
bare entries:       1814
context entries:      10
-v entries:          749
source units:        2563
total entries:       2573
inferred root:          /
server pyslang:      11.0.0
```

`-v` 只占 source unit 的一部分，供应商或第三方代码也可能以裸路径进入；因此不能用“是否带 `-v`”判断
文件归属或改写权限。

## 5. 第一次资源失败：20 GiB cgroup SIGKILL

登录 / 普通交互会话属于 cgroup v1：

```text
cgroup: /users/maoyiming
memory.limit_in_bytes:     21474836480
memory.max_usage_in_bytes: 21474836480
memory.failcnt:            1385663
```

内核记录：

```text
Memory cgroup out of memory: Kill process ... (python)
Killed process ... total-vm:20941976kB, anon-rss:20586828kB
```

T122 后用 `/usr/bin/time -v` 复测：

```text
Command terminated by signal 9
Maximum resident set size (kbytes): 20591716
```

当时整机仍有数十 GiB available memory，但进程所在 cgroup 的 20 GiB 上限已经耗尽，所以这是作业级
限制触发的 OOM kill，而不是 Python 正常异常或 PySlang diagnostic。

T122 前后峰值只相差约数 MiB，证明有界诊断读取修复是正确的局部修复，但没有改变主内存曲线。

## 6. LSF/OpenLava 大内存运行证据

用于获得独立计算资源的交互作业形式为：

```sh
bsub \
  -q inta \
  -P ABC \
  -Is \
  -n 1 \
  -R "span[hosts=1] rusage[mem=65536]" \
  bash
```

注意：`rusage[mem=65536]` 是 64 GiB 调度资源申请 / 预留，不等同于该进程的硬内存上限。首次进入的
作业 `113290` 被调度到 `BJ-IDC1-10-10-18-133`，所在 memory cgroup 显示接近无穷大的 limit sentinel。
实际高内存复测作业号为 `113476`；当时计算节点显示约 2.2 TiB 总内存、约 1.2 TiB available。

运行进度：

```text
[   1.672s] 开始 读取 filelist / 组装 SourceSet
[1817.390s] 完成 读取 filelist / 组装 SourceSet（本阶段 1815.719s）
[1817.998s] 开始 PySlang 编译与 elaborate
```

最终结果：

```text
error: CLI_VNEXT_ORCHESTRATION_INVALID
detail: ORCHESTRATION_MAPPING_INVALID
message: REFUSED_ATOMIC: module has multiple physical declarations:
  ADDF_D1_N_S6P25TL_C54L04

Maximum resident set size (kbytes): 628545712
Exit status: 1
```

628,545,712 KiB 约等于 599.4 GiB。该进程没有被 64 GiB 杀死，而是在项目的重复声明检查中主动失败。
作业结束后 `bjobs -l` 显示的约 18 MiB 是仍存活交互 shell 的当时用量，不是已退出 Python 子进程的峰值；
峰值证据应以 `/usr/bin/time -v` 为准。

## 7. 当前直接阻塞：同名 module 的两份物理声明

服务器定位到两处：

```text
/project/STPU2/maoyiming/work/s5_code/ChipPlatform/common/src/StdLib/rtl/
  ln04lpp_sc_s6p25t_flk_lvt_c54l04.v:54

/library/SF4/install/pdk/MODEL/flk/
  ln04lpp_sc_s6p25t_flk_lvt_c54l04.v:54
```

两处都声明：

```systemverilog
module ADDF_D1_N_S6P25TL_C54L04 (CO, S, A, B, CI);
```

目前只确认 module 名称和声明位置相同，尚未取得两文件的 hash / `cmp` 证据，因此不能声称两份文件
字节完全相同，也不能自行选择任意一份。

当前项目的 duplicate check 对同名 module 的任何两份物理声明一律 fail closed。对普通 source input 这是
安全策略；但真实 filelist 中一份可能是工程内拷贝、另一份可能是 `-v` library provider。由于 parser 已经
抹掉 `-v` 来源，后续既无法模拟 library 按需选择，也无法根据 filelist 语义解释哪一份应生效。

## 8. 内存为什么会被放大

当前代码路径中的关键点：

1. `project_discovery.compile_pyslang_source_set()` 把全部 `compilation_files` 一次传给
   `SyntaxTree.fromFiles()`，创建一个 `Compilation`，调用 `getRoot()` 和 `getAllDiagnostics()`；
2. `source_catalog.build_source_catalog()` 首先调用 `_compile_view(..., top=None)`，不是用户提供的
   `AIClusterWrapper`；
3. 未指定 top 时，大量没有被其它模块实例化的标准单元和供应商叶子模型可能都成为顶层候选并被
   elaborate；当前 `-v` 文件已被当作普通 source unit，无法保持按需库行为；
4. `_module_definitions_for()` 会把整个 semantic root 的遍历结果保存到 Python `list`；
5. `_check_duplicate_syntax_modules()` 会把整个 CST 的遍历结果保存到另一个 Python `list`，并在这里发现
   当前重复 module；
6. 如果 duplicate check 通过，代码还会再执行一次带用户 top 的 `_compile_view()`；RenameIndex 也有多处
   整树 `visit(nodes.append)`；
7. MappingVNext 通过 RenameIndex / SourceCatalog 保留原 Compilation 身份；gate 阶段又会建立 gate
   catalog；rewrite / restore 阶段还会把全部物理文件 bytes 放入字典。

最新失败发生在第 5 步，早于第二次 top overlay、RenameIndex、gate compilation 和 restore。因此 599 GiB
不是完整成功流水线的已知上限；如果不先改变架构，仅继续增加内存仍可能在后续阶段出现更高峰值。

## 9. “PySlang 固有问题”与“项目问题”的边界

| 部分 | 当前判断 | 证据强度 |
| --- | --- | --- |
| 大型 HDL 语法树、语义树和 elaborate 本身占内存 | PySlang / 编译任务的基础成本 | 已观测约 20 GiB，但尚未做独立 parse-only 分解 |
| 把 2563 个 source unit 一次加入同一 Compilation | 当前项目的输入策略 | 代码已确认 |
| 抹掉 `-v` provenance，并按普通 source 处理 | 当前项目的兼容边界 | T117 合同与代码已确认 |
| 先执行 `top=None` 全 catalog elaborate | 当前项目的 catalog 设计 | 代码已确认 |
| 整棵 semantic/CST 树复制引用到 Python list | 当前项目的索引实现 | 代码已确认 |
| 保留多个 Compilation 并在 gate 再编译 | 当前项目的对象生命周期设计 | 代码已确认，当前服务器运行尚未走到全部阶段 |
| PySlang 11.0.0 存在泄漏 | 未证明 | 需要隔离测量，当前不得下结论 |

当前最准确的描述是：PySlang 承担重型语义模型的基础成本，而项目没有保存 library 语义、使用无 top 的
全库 elaborate、整树 materialization 和长生命周期对象，使这个成本在真实 filelist 上发生病理性放大。

## 10. `--rewrite-root` 的已知归属风险

实际命令使用：

```text
--rewrite-root /project/STPU2/maoyiming/work/s5_code/ChipPlatform
```

但重复声明的一份文件位于该 root 内的：

```text
common/src/StdLib/rtl/
```

这说明“ChipPlatform 下都是自研、可改写代码”并不成立。T121 只会自动保护命中特定供应商诊断的文件；
若一个嵌套供应商 / 标准库文件语法干净，它仍可能落入 rewrite eligibility。

后续必须由用户确认真正允许改写的一个或多个子目录，或冻结清晰的 include / exclude / readonly 规则。
在确认前，不应把当前广义 `ChipPlatform` root 当作安全的生产加密边界。

## 11. 尚未决定的问题

以下均保留到后续讨论，本记录不选方案：

1. 是否完整保留 filelist entry mode，使 `-v` 在原始和 gate `design.f` 中仍是 `-v`，并实现哪一级 lazy
   library search；
2. 同名 definition 在 `-v + -v`、裸路径 + `-v`、裸路径 + 裸路径和不同 PVT 库版本下如何选择；
3. 是否引入独立 `analysis_compile_order`，同时完整保留物理 `compile_order` 用于输出和真实 simulator；
4. analysis 范围由显式 `--analysis-root` 指定，还是从 `--rewrite-root` 和 top 自动计算依赖闭包；
5. 范围外 module 使用接口 stub、轻量 definition index、受控 unresolved reference，还是其它机制；
6. package、interface、typedef、macro、include 及 parameter 依赖如何精确带入分析集合；
7. 怎样确保 excluded module 的端口 / parameter 绑定不会导致错误改名，同时对拼写错误继续 fail closed；
8. 是否把 PySlang 编译放入短生命周期子进程，Mapping 是否可以不再持有 live Compilation；
9. 如何流式执行 duplicate inventory、semantic/CST 访问、rewrite、gate 和 restore；
10. scoped analysis 在报告中如何明确表达，避免被误解为完整 filelist 的严格 semantic compile。

## 12. 后续方案必须满足的边界

无论选择哪条路线，至少应保持：

- `-v` 不自动等于只读，也不自动等于可改写；来源语义和改写权限必须分开；
- 供应商精确语法放行继续 fail closed，不扩展成庞大通用兼容层；
- 所有最终 edit 必须位于明确允许的 rewrite root，范围外文件 byte-identical；
- 不允许仅按路径猜测后静默选择重复 module；必须有确定、可报告的 provider 规则；
- top 必须存在于 analysis 集合；依赖缺失、歧义或错误拼写不得被统一吞掉；
- 若使用局部分析，报告必须明确列出完整输入、分析输入、只读输入、被排除 definition 和原因；
- gate 输出必须保留真实 downstream simulator 所需的 filelist / include / define / library 语义；
- 原子失败语义保持：失败不得发布半成品输出；
- 先增加分阶段 RSS / HWM 和对象数量测量，再做下一次完整服务器大内存运行；
- 在内存护栏和早期 duplicate inventory 完成前，不应重复一次约 599 GiB 的盲跑。

## 13. 候选分阶段方向（未冻结）

后续可按以下顺序讨论，但这些不是已批准合同：

1. **测量与早期清单**：在建立重型 Compilation 前，流式记录 filelist provenance、module provider、重复定义
   和分阶段 RSS / HWM；
2. **恢复 library 语义**：保留 `-v` entry 类型与顺序，冻结重复 provider 的选择 / 拒绝规则；
3. **缩小 semantic analysis**：建立独立 analysis set，只 elaborate top 与允许改写代码所需的精确闭包，
   外部实现保持只读并用受控接口信息参与绑定；
4. **降低驻留峰值**：避免全树 Python list，缩短 Compilation 生命周期，必要时用子进程隔离原始和 gate
   compilation，并流式处理物理文件；
5. **服务器验收**：先做只读 compile / mapping dry run，再做 gate / restore；记录每阶段时间、RSS、输出原子性
   和完整 downstream simulator 结果。

## 14. 当前验收与 Formal 状态

```text
current_real_filelist_result: BLOCKED
first_blocker: 20 GiB login-session memory cgroup; bypassed with LSF/OpenLava job
latest_blocker: duplicate physical module declaration after approximately 599.4 GiB peak RSS
mapping_created: no
gate_created: no evidence
restore_created: no
formal_verification: N/A
reason: failure occurred before mapping/gate; server validation flow does not use Yosys Formal
```

CLI 报告了 `REFUSED_ATOMIC`，说明失败走的是原子拒绝路径；但服务器未提供对 `$OUT` 的事后目录检查，
所以本记录不把“输出目录一定不存在”写成已独立验证的事实。

## 15. 继续讨论前建议补充的低成本证据

后续无需立刻再跑完整编译，可先收集：

1. 两份重复库文件的 `sha256sum`、`cmp` 结果及其各自在展开后 filelist 中的原始 entry 形式和顺序；
2. 真正允许改写的最小目录列表，以及 `ChipPlatform/common/src/StdLib` 是否应永久只读；
3. 展开后的 `-v` / bare / context entry 清单，保留来源 filelist、嵌套层级和顺序；
4. 目标工程最终使用的 simulator 对 `-v`、重复库和库选择的实际规则；
5. 如果再次运行，至少在 SourceSet、syntax parse、`getRoot(top=None)`、diagnostics、CST inventory、
   explicit-top compile、RenameIndex、gate compile 前后分别记录 elapsed time、`VmRSS` 和 `VmHWM`。

这些证据用于下一轮方案选择，不构成当前实现任务。
