# T029：RISC-V-Vector 真实工程加密与 formal-view 交付

- 状态：`ACCEPTED`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T028 `ACCEPTED`
- 实现基线提交：`9386135`
- 路线图：[`docs/project_root_top_roadmap.md`](../project_root_top_roadmap.md)
- Formal verification：必须 `PASS`

## 1. 单一目标

在不修改固定样例 `rtl_samples/RISC-V-Vector/` 的前提下，让 T027/T028 的通用
`project-root + top` 能力对 `vector_top` 完成一次真实的、可审计的工程级交付：

1. 修正真实工程暴露的五项漏收 source range；
2. 对 `signals/ports/instances/struct/interface` 五组执行组合加密；
3. 严格重编译 gate，证明 17 个 reachable module、19 个 closure file 和实例拓扑不变；
4. 校验 mapping/metrics、top ABI、解密逐字节恢复和所有固定 oracle；
5. 对 gold/gate 对称生成确定性的 Yosys formal view，并对 gate 生成可审计的 formal-only
   identifier alignment；
6. 使用真实 gate 派生链运行 Yosys 等价正例和功能负例；
7. 更新正式用户文档，把 `project-root + top` 能力从计划状态变为已交付状态。

本任务仍不重命名 parameter、module、top module、top ports 或 top ABI struct；不解析
Vivado/Quartus Tcl、IP catalog、预编译库、DPI、class、bind、checker、primitive、testbench、
SDC 或外部层次引用。

T029 是一张粗粒度交付合同，不再拆分 inventory 修正、formal view、真实工程加密和文档任务。
只有整张合同全部通过后才发生一次 `READY_FOR_REVIEW -> ACCEPTED` 交接。

## 2. 子 Agent 角色

子 Agent 是实现者和自测者，不是需求制定者、fixture 维护者或最终验收者。

子 Agent 必须：

- 完整阅读 `AGENTS.md`、`docs/tasks/README.md`、T027/T028 合同、本合同、路线图、
  `docs/formal_verification.md`、`docs/systemverilog_renaming_table.md` 和根目录 `README.md`；
- 确认 T029 是唯一 `READY` 任务，然后先把本文件状态改为 `IN_PROGRESS`；
- 在执行记录中写明开始时间、HEAD、首条命令和工作区状态；
- 严格按第 16 节阶段顺序执行，阶段门禁失败时停止后续阶段；
- 只修改第 20 节允许文件；
- 保持 RISC-V-Vector、T027 fixtures、example FIFO 和旧测试只读；
- 所有 Python、parser、HDL、test 和 Yosys 命令使用 Conda 环境 `rtl_obfuscation`；
- 记录 exact command、exit code、JSON、SHA-256、formal 正负结果和未覆盖边界；
- 全部门禁通过后只设置 `READY_FOR_REVIEW`；
- 不得设置 `ACCEPTED`，不得 commit、push 或创建下一任务。

主 Agent 负责独立运行第 19 节全部门禁、解释合同、设置 `ACCEPTED` 和 Git 交付。

## 3. READY 基线、已证实缺口和授权修正

### 3.1 固定分析基线

在提交 `9386135` 上，下面命令成功：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite inspect-project \
  --project-root rtl_samples/RISC-V-Vector \
  --top vector_top \
  --report /tmp/t029_ready_gold_report.json
```

当前报告为 56 candidates、19 closure files、17 reachable modules、0 interfaces、0 parse error、
0 semantic error、1085 eligible symbols、5378 eligible occurrences。READY 时已知的前三项错误和
Phase B 主 Agent 复核新增的两项错误使后两个 inventory 数字不完整，本任务明确授权最小修正。

### 3.2 signals：generate-local actual argument 漏收

`eb_buff_generic.gen_fifo` 中 `fifo_push`、`fifo_pop` 的声明和 assign 已被收集，但作为
`fifo_duth` 实例 actual argument 的下面两个语义绑定引用未被收集：

| symbol | file | start | end |
| --- | --- | ---: | ---: |
| `fifo_push` | `rtl/shared/eb_buff_generic.sv` | 2362 | 2371 |
| `fifo_pop` | `rtl/shared/eb_buff_generic.sv` | 2515 | 2523 |

遗漏会让 signals-only gate 产生两个新的 implicit net。必须通过 PySlang 的 resolved connection/
symbol identity 收集这两个位置；不得按名字扫描所有 instance connection。

### 3.3 ports：packed aggregate member base 漏收

当前 port collector 只收集普通 `NamedValueExpression` 和 named connection 左侧端口名，没有收集
`aggregate_port.field` 中语义上绑定到 port internal symbol 的 base。RISC 闭包中共有 223 个唯一
物理位置，分布如下：

| scope | port | 新增 references |
| --- | --- | ---: |
| `vex` | `exec_info_i` | 11 |
| `vis` | `info_to_exec` | 7 |
| `vis` | `instr_in` | 44 |
| `vmu` | `instr_in` | 8 |
| `vmu` | `mem_req_o` | 5 |
| `vmu` | `mem_resp_i` | 6 |
| `vmu_ld_eng` | `instr_in` | 20 |
| `vmu_st_eng` | `instr_in` | 19 |
| `vmu_tp_eng` | `instr_in` | 23 |
| `vrrm` | `instr_in` | 35 |
| `vrrm` | `instr_out` | 31 |
| `vrrm` | `m_instr_out` | 14 |

必须从 `MemberAccessExpression.value` 取得 port internal symbol 和精确 base range；不得把右侧
struct field range误记到 ports，也不得根据 diagnostic 文本补位置。

Phase B 复核还确认下面两类 port reference 漏收。它们与上表 223 个位置互不重复，共再增加
118 个 references。

#### 3.3.1 syntax-less NamedValue 的精确 source range

PySlang 已为下面 104 个唯一物理位置产生 `NamedValueExpression`，其 `symbol` 与对应 port 的
`internalSymbol` 是同一对象，但其 `syntax` 为 `None`。当前 collector 只在
`syntax.identifier` 存在时记录范围，因此遗漏这些位置。必须只在 symbol identity 已匹配后，
以该 `NamedValueExpression.sourceRange` 作为 fallback，并继续通过源文件 bytes 精确校验名字；
不得按名字或 diagnostic 反推范围。

| file | 新增 references |
| --- | ---: |
| `rtl/shared/and_or_mux.sv` | 3 |
| `rtl/vector/v_int_alu.sv` | 31 |
| `rtl/vector/vex.sv` | 11 |
| `rtl/vector/vex_pipe.sv` | 2 |
| `rtl/vector/vis.sv` | 24 |
| `rtl/vector/vmu.sv` | 12 |
| `rtl/vector/vmu_ld_eng.sv` | 9 |
| `rtl/vector/vmu_st_eng.sv` | 2 |
| `rtl/vector/vmu_tp_eng.sv` | 3 |
| `rtl/vector/vrf.sv` | 7 |
| **合计** | **104** |

子 Agent 报告的 71 个 `UndeclaredIdentifier` 只是失败编译实际发出的首批 diagnostics，不是完整
oracle。另有 31 个 `v_int_alu.sv` 和 2 个 `vex_pipe.sv` 明文位置可由同一 symbol-identity 条件
直接枚举；只补 71 个会留下不完整 mapping。

#### 3.3.2 uninstantiated generate actual 中的父模块 ports

`eb_buff_generic` 的未展开 generate 分支不会为父模块 port actual 产生可用
`NamedValueExpression`。当前 signal 修正使用 `parentScope.find()` 只找到 branch-local signal；
父模块 port 需要在同一 lexical scope 上回退 `lookupName()`，并将解析到的 port internal symbol
映射回唯一 port target。只有 identity 匹配后才能记录 identifier token。

固定新增 14 个 references：

| branch | port actuals | file ranges |
| --- | --- | --- |
| `gen_two_slot_eb` | `clk/rst/valid_i/ready_o/data_i/valid_o/ready_i/data_o` | `1605:1608, 1638:1641, 1684:1691, 1717:1724, 1750:1756, 1796:1803, 1829:1836, 1862:1868` |
| `gen_fifo` | `clk/rst/data_i/ready_o/data_o/valid_o` | `2244:2247, 2279:2282, 2327:2333, 2397:2404, 2445:2451, 2480:2487` |

以上范围均位于 `rtl/shared/eb_buff_generic.sv`。不得把未展开分支中的未知 child module port
spelling 当作 reachable port，也不得扩大 hierarchy closure。若缺少这 14 个 actual，单组
ports gate 虽可只按 ports 类通过审计，五组 combined gate 会把它们误建为 14 个额外 signal，
从而变成 1105 个 eligible symbols 并失败。

### 3.4 struct：packed array element alias 漏收

`to_vector_exec [VECTOR_LANES-1:0]` 的语义类型是 `PackedArrayType`，其 `elementType` 是
compilation-unit packed struct alias `to_vector_exec`。当前实现只检查
`declaredType.type is alias`，因此漏掉该 type 和五个 field。

本任务授权递归穿过本样例中的单层 `PackedArrayType` wrapper，找到唯一 aggregate element alias。
遇到 unpacked、嵌套或多 aggregate element type 仍按未支持边界处理。RISC 固定新增：

- `struct_types`：`$unit::to_vector_exec`，1 symbol / 5 occurrences；
- `struct_fields`：`valid/mask/data1/data2/immediate`，5 symbols / 15 occurrences；
- 四个 type references 分别位于 `vector_top.sv` 两处、`vex.sv` 一处、`vis.sv` 一处；
- 每个 field 有 declaration + `vex` reference + `vis` reference，共 3 occurrences。

不得借此加入 enum、union_fields、package/class type、tagged union 或 parameter 重命名。

### 3.5 Yosys 0.53 边界

READY 探针已证明：

1. 原闭包直接读入时，`fifo_duth.sv:97` 的 `assert property` 在 `@` 处失败；
2. 只移除两条 assertion 后，Yosys 仍在 compilation-unit packed struct 的 port/field access 上
   触发 `genrtlil.cc:1604` 内部断言；
3. 对 7 个 reachable compilation-unit packed struct 做第 12 节的等宽 packed-logic lowering 后，
   `read_verilog -sv -formal -defer` 和 `hierarchy -check -top vector_top` 成功；
4. multifile formal 还必须对称使用 `-defer`，并在两侧 `prep` 后执行 `async2sync`；
5. READY identity 可行性探针在 `--seq 1` 下证明 35029/35029 `$equiv`，约 3 分钟、峰值约
   2.5 GiB；该 identity 结果只证明合同可执行，不得作为最终 gate formal 证据；
6. 把 `vector_idle_o` 表达式第一个 `&` 改成 `|` 后退出 1，最终留下 1 个未证明 cell。

本任务因此授权 AST 驱动的 formal-only lowering；不得修改 gold/gate 产品 RTL 来迎合 Yosys。

## 4. 固定 RISC 输入 manifest

固定 root：

```text
rtl_samples/RISC-V-Vector
```

固定 top：

```text
vector_top
```

产品输入 manifest 算法与 mapping v3 相同：对 sorted relative file list 生成
`<file_sha256><two spaces><relative_path>\n`，再对拼接 bytes 做 SHA-256。

固定 19 个 closure file：

| SHA-256 | relative file |
| --- | --- |
| `fb9a2123d2ace8375d9f7842eb13bb63710db4af17b295731a04f5496a7c6297` | `rtl/shared/and_or_mux.sv` |
| `4fd09b91b7b4d4509b12b7bbb9ced17c9fe99dc23ab8cf4eb5591d3c07adcc08` | `rtl/shared/eb_buff_generic.sv` |
| `0347799817d75bfd73bcec5d080e0573b18772dfd3d5065c4c7a71b3805efad2` | `rtl/shared/eb_one_slot.sv` |
| `76f408780d2e4d64e2d5e732e569b65b90a85b879ed545514c7d55991cf93896` | `rtl/shared/fifo_duth.sv` |
| `5a99d903e3ede7d506a854b515142d8d019f651d530e62b7e99b708a54785f6a` | `rtl/vector/v_fp_alu.sv` |
| `cb7260028e606a64fcccf8a24520440dcb272968ab5f9ca0b5443cc28430059b` | `rtl/vector/v_int_alu.sv` |
| `3cb76a98feba84595d83289a84f0ca14c62f2958b25f61329fa2fcbe6a2f7356` | `rtl/vector/vector_top.sv` |
| `8074cc809ddb28e4ad49b42ad1a3368d4304a8888e494236e85c9d7e699fcb00` | `rtl/vector/vex.sv` |
| `cff8851a2399bd0fcbcf7e98f5edbcc3a0487cc77bd18668c589042bfdfe48af` | `rtl/vector/vex_pipe.sv` |
| `89a70832dcd2e93299602183daddfacb89e6c99ecfe5065f3ed675282b5ea465` | `rtl/vector/vis.sv` |
| `0472e17ca030d07e8d4f5c888cf6f185380490f5f3a4ce36de03bd27672491f9` | `rtl/vector/vmacros.sv` |
| `07603adbd782c26c7dd715017edbb77c1fb6d41b5ad8e0a244decfc5b930169e` | `rtl/vector/vmu.sv` |
| `0ca300d3799b25a18193054f4c03b24e422935327088e1f8ec73e9ace78b82f0` | `rtl/vector/vmu_ld_eng.sv` |
| `2ccbcc5d340361a7b9c787b7a883a074a96c79c5c3fe5a93d6978aa189c8a0c5` | `rtl/vector/vmu_st_eng.sv` |
| `77a39d9417a3057474b33d18c548bc4cca13aa16ee3edae11e5c3651f95f7d49` | `rtl/vector/vmu_tp_eng.sv` |
| `50bfe196b321dbb9ed391fdf930932a8808fb298db8b026758f7e70d786a939b` | `rtl/vector/vrat.sv` |
| `20e5a2c56a16ea0c94a7b029690b668330f7821dbfa415be6452077dc1111ec3` | `rtl/vector/vrf.sv` |
| `0a2672145292761eec4068343e06f91d60fa56df3122aa56fb052848098b8f03` | `rtl/vector/vrrm.sv` |
| `9fb26c38f36faa5ff6da77fa77b94a971aeeba2c61911cf75362af7bb955512a` | `rtl/vector/vstructs.sv` |

固定 aggregate manifest：

```text
a016dd548525346508c636b97fcc452c8f6eb4fcbf930ef5eb938a2edfa2ae9d
```

任一输入 bytes 变化时，测试和验收驱动必须先失败，不能重新从变化后的输入生成 oracle。

## 5. 固定 closure、compile order 和拓扑

固定 sorted reachable modules：

```text
and_or_mux
eb_buff_generic
eb_one_slot
fifo_duth
v_fp_alu
v_int_alu
vector_top
vex
vex_pipe
vis
vmu
vmu_ld_eng
vmu_st_eng
vmu_tp_eng
vrat
vrf
vrrm
```

固定 compile order 和 formal `design.f` 内容：

```text
rtl/shared/and_or_mux.sv
rtl/shared/eb_one_slot.sv
rtl/shared/eb_buff_generic.sv
rtl/shared/fifo_duth.sv
rtl/vector/v_fp_alu.sv
rtl/vector/vmacros.sv
rtl/vector/v_int_alu.sv
rtl/vector/vex_pipe.sv
rtl/vector/vrat.sv
rtl/vector/vrf.sv
rtl/vector/vstructs.sv
rtl/vector/vex.sv
rtl/vector/vis.sv
rtl/vector/vmu_ld_eng.sv
rtl/vector/vmu_st_eng.sv
rtl/vector/vmu_tp_eng.sv
rtl/vector/vmu.sv
rtl/vector/vrrm.sv
rtl/vector/vector_top.sv
```

末尾必须有一个 LF；该 `design.f` SHA-256 固定为：

```text
0b15939236d3ac1ceb490b998afe5fdab332e91caddc552f1009847adfab9e96
```

gold/gate 必须有完全相同的 relative closure files、compile order、reachable module set、module
definition/instance parent-child topology和 include/define context。不得编译全部 56 candidates 后过滤。

## 6. 最终 inventory oracle

### 6.1 canonical digest 算法

测试对 `report["inventory"]["eligible"]`、`preserved` 和完整 `inventory` 使用：

```python
hashlib.sha256(
    json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
).hexdigest()
```

list 顺序属于 oracle；不得先自行重排再比较。每个 entry 的 category/scope/name/declaration/
references/occurrences/reason 都参与 digest。

最终固定：

```text
eligible:  1091 symbols / 5741 occurrences
eligible_sha256: 6d4e0ef7d46d569d2fecda8563ccdd4012eb6043cb86b9c908d06391b291e6d0
preserved: 35 symbols / 113 occurrences
preserved_sha256: b5b31416d834ff03eda28e28c4e625108b13e36ecdf28750dc5d78f22e244d9f
inventory_sha256: 0b661f775f936cb15ca5c39dbafbb54c450a5062a935d7daac2d16113d6b3e93
```

### 6.2 category oracle

| actual category | eligible symbols | eligible occurrences | eligible canonical SHA-256 | preserved symbols | preserved occurrences |
| --- | ---: | ---: | --- | ---: | ---: |
| `signals` | 675 | 3614 | `edefb29037c1f7c08eb017494ed6a12bb67948c9c86ac2077e2238504327dc1e` | 0 | 0 |
| `ports` | 348 | 1853 | `2dad5d96fdc98cc95a6285e2bfcad97fbc628e81849a9d91cf1d43a6c7a61d63` | 11 | 37 |
| `instances` | 19 | 19 | `0c13b299ea5655ceadc75a25d7146a24f956932ccae4ee9d68ba01024cf18da5` | 0 | 0 |
| `struct_types` | 4 | 23 | `8e4282cf409eaaf2edc39ad00f7385cb72b2229a11ba8c13f5ffafb19cbb2b1a` | 3 | 9 |
| `struct_fields` | 45 | 232 | `537835deb4ba9c07c64848d0a1a9688ca67549f1ea65f1b7a01f3b6df9a772d2` | 21 | 67 |
| `interfaces` | 0 | 0 | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` | 0 | 0 |
| `interface_instances` | 0 | 0 | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` | 0 | 0 |
| `interface_ports` | 0 | 0 | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` | 0 | 0 |
| `modports` | 0 | 0 | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` | 0 | 0 |

固定 preserved category digests：

```text
ports:        9502c607a991e6ff7c684c57f6b5d7bc7e9d5155246811e82dc4e7027837fb39
struct_types: df08eeb44d7de0f3dfb54729d3b2a695f8efd7cb4d6c8e35ac87c241e227458a
struct_fields:f2dee738d981118ee4ca91513da7bdd9ca83bd127cf5543625daa4d915860499
```

### 6.3 用户组 oracle

| group | mapping entries | modified tokens |
| --- | ---: | ---: |
| `signals` | 675 | 3614 |
| `ports` | 348 | 1853 |
| `instances` | 19 | 19 |
| `struct` | 49 | 255 |
| `interface` | 0 | 0 |
| combined five groups | 1091 | 5741 |

interface=0 是合法的真实工程结果，仍必须出现在 selected groups/categories、debug matrix 和
formal acceptance 中；不得伪造 interface fixture 到 RISC 闭包。

## 7. top ABI 和不改写边界

必须保留：

- top module `vector_top`；
- 11 个 top ports，共 37 occurrences：`clk/rst_n/vector_idle_o/valid_in/instr_in/pop/`
  `mem_req_valid_o/mem_req_o/cache_ready_i/mem_resp_valid_i/mem_resp_i`；
- top ABI struct types `to_vector/vector_mem_req/vector_mem_resp`，3/9；
- 对应 21 个 top ABI fields，21/67；
- 所有 parameter/localparam 和 module 名；
- closure 外文件和同文件不可达定义。

mapping entries 中 parameter 必须为 0。preserved 必须仍为 35/113，reason 只能是已验收的
`top_port` 或 `top_abi_type`。top module 和 top ports 在 gold/gate 必须逐 token 同名；解密后 19
个 closure file 必须逐字节恢复。

## 8. RISC 组合加密合同

固定命令：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-project \
  --project-root rtl_samples/RISC-V-Vector \
  --top vector_top \
  --output-dir /tmp/rtl_obfuscation_t029/gate \
  --map /tmp/rtl_obfuscation_t029/mapping.json \
  --metrics /tmp/rtl_obfuscation_t029/metrics.json \
  --file-map-dir /tmp/rtl_obfuscation_t029/maps \
  --category signals \
  --category ports \
  --category instances \
  --category struct \
  --category interface \
  --name-length 8
```

固定成功 stdout：

```json
{"files": 19, "mapping_entries": 1091, "modified_tokens": 5741}
```

必须满足 T028 mapping v3 schema、manifest、事务发布、per-file map 和 decrypt 合同；不能为 RISC
增加私有 mapping 字段或特殊 category。gate strict inspect 必须为 0/0 diagnostics、1091/5741
renamed inventory、17 modules、19 files。metrics 固定：

```text
symbols: total=1091, renamed=1091, coverage=1.0
occurrences: total=5741, renamed=5741, coverage=1.0
plaintext_leakage_rate=0.0
```

plaintext leakage 必须覆盖本任务新增 `to_vector_exec` type/fields，不能只在旧的 1085 对象上算
1.0。

## 9. 解密和 hash 验收

固定命令：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt-project \
  --gate-dir /tmp/rtl_obfuscation_t029/gate \
  --map /tmp/rtl_obfuscation_t029/mapping.json \
  --output-dir /tmp/rtl_obfuscation_t029/restored
```

stdout 必须同样为 19/1091/5741。验收驱动必须对 mapping `files` 中每个文件比较 bytes 和
SHA-256，最终 restored manifest 必须等于固定 input manifest
`a016dd548525346508c636b97fcc452c8f6eb4fcbf930ef5eb938a2edfa2ae9d`。

## 10. formal-view 用户 CLI

新增命令：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite formal-view \
  --project-root <gold-or-gate-root> \
  --top <top-module> \
  --output-dir <view-dir> \
  --manifest <formal-view.json> \
  [--include-dir <directory>]... \
  [--define <NAME-or-NAME=VALUE>]...
```

固定规则：

- 复用同一 project resolver、closure、strict compilation 和 selected top traversal；
- `--output-dir`、`--manifest` 不得位于输入 root 内，不得覆盖输入；
- 输出目录包含 closure files 和 `design.f`；不复制无关文件；
- 输出和 manifest 事务式发布，失败时都不存在或保持原值；
- 生成 view 后必须调用当前环境 Yosys，以 `read_verilog -sv -formal -defer` 和
  `hierarchy -check -top <top>` 验证；失败时 formal-view 命令退出 1；
- stdout 固定为 JSON summary：`files/top/transformations/view_manifest_sha256`；
- 不增加网络、插件、Surelog、sv2v、yosys-slang 或其他依赖。

formal view 是验证派生物，不是加密 gate，不参与 decrypt，也不得写回 project root。

## 11. formal-view manifest v1

顶层字段必须精确为：

```json
{
  "version": 1,
  "mode": "formal-view",
  "top": "vector_top",
  "source_files": [],
  "compile_context": {
    "compilation_unit": "single",
    "include_dirs": [],
    "defines": [],
    "compile_order": []
  },
  "source_manifest_sha256": "",
  "view_manifest_sha256": "",
  "design_file": "design.f",
  "transformations": []
}
```

不得记录绝对路径、时间戳、随机 id 或临时目录。

每个 transformation 的公共字段：

```json
{
  "kind": "",
  "file": "rtl/vector/vex.sv",
  "start": 0,
  "end": 1,
  "syntax_kind": "",
  "structural_ordinal": 0,
  "source_sha256": "",
  "replacement_sha256": ""
}
```

variant 附加字段：

- `lower_packed_aggregate_type`：`bit_width`；
- `lower_packed_struct_member`：`struct_width/field_offset/field_width/base_shape`；
- `remove_concurrent_assertion`：没有附加字段。

`structural_ordinal` 是同一 `(file, kind)` 下按输入 source start 排序的零基序号。gold/gate 对称
检查使用下列 signature，明确忽略因重命名产生的 start/end 和 source/replacement hash 差异：

```text
type:      kind,file,syntax_kind,structural_ordinal,bit_width
member:    kind,file,syntax_kind,structural_ordinal,struct_width,field_offset,field_width,base_shape
assertion: kind,file,syntax_kind,structural_ordinal
```

除此之外所有字段必须严格校验。source/replacement hash 是 transformation 对应 bytes 的
SHA-256；range 必须位于 source file 内且无重叠。

## 12. formal-view 允许变换

### 12.1 aggregate type lowering

只对 selected top 树中实际使用的 compilation-unit packed struct alias 及其 packed array wrapper
做 formal-only lowering。RISC 固定 7 个语义类型：

```text
to_vector
remapped_v_instr
memory_remapped_v_instr
to_vector_exec
to_vector_exec_info
vector_mem_req
vector_mem_resp
```

对每个物理 declared type syntax，使用 PySlang elaborated `bitWidth`，整个 type syntax 精确替换为：

```text
logic [<bit_width-1>:0]
```

RISC 固定 25 个唯一 type lowering。不得修改 typedef declaration 本身，不得 lower enum、普通
logic、parameter type 或未被 selected top 使用的类型。

### 12.2 packed struct member lowering

字段宽度和 offset 必须来自 PySlang `FieldSymbol.type.bitWidth` 和 `FieldSymbol.bitOffset`。

scalar base 固定模板：

```text
<base>[<field_offset> +: <field_width>]
```

单层 packed-array element base 固定模板：

```text
<base>[((<selector>)*<struct_width>+<field_offset>) +: <field_width>]
```

RISC 只允许 `NamedValueExpression` 和单层 `ElementSelectExpression` 两种 base shape，共 233 个
唯一物理 member lowering。遇到 nested member、multi-dimensional selector、variable part-select、
union、unpacked struct 或无法唯一映射 source range 时必须退出 1，不得猜测。

### 12.3 concurrent assertion removal

只允许完整 blank 掉 `ConcurrentAssertionStatementSyntax`，每个非 LF byte 替换为空格，LF 保留。
固定两项：

| file | start | end | source SHA-256 |
| --- | ---: | ---: | --- |
| `rtl/shared/fifo_duth.sv` | 2484 | 2584 | `020bf14fe0b01ea83a5c6dd513a8a0a781f996b2775a2003a4b486d5db1c1658` |
| `rtl/shared/fifo_duth.sv` | 2585 | 2685 | `c21c586ccc992be0bf7fc488d8e16310f5440bd10571b5b5cd4b884e4502c667` |

不得删除 immediate assertion、声明、assign、always、initial、generate、module、interface 或数据通路。

### 12.4 固定 view oracle

RISC gold view 固定：

```text
lower_packed_aggregate_type = 25
lower_packed_struct_member  = 233
remove_concurrent_assertion = 2
total transformations       = 260
view file manifest SHA-256  = 56572fb29266c2f6cb44ef9a9846bda4585c846dc28677b9855e9bae79649872
```

view manifest hash 使用第 4 节相同算法，只覆盖 19 个 RTL closure files，不覆盖 `design.f` 或
manifest JSON。相同输入连续两次生成的 19 个 files、`design.f`、manifest JSON 必须逐字节相同。

### 12.5 mapping 辅助的 formal-only identifier alignment

真实 gate 的 1091 个内部对象已经随机改名，直接送入 `equiv_make` 会在
`equiv_struct -icells` 后留下 67168 个未证明 cells，逐项 SAT 无法在 600 秒内完成。Phase D
主 Agent 探针确认：只对 gate formal view 的 identifier token 应用已验证 mapping 的
`renamed_name -> original_name`，可以恢复等价工具的 name matching，同时不改变任何功能 token。

本任务新增独立验证派生步骤 `formal-align`：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite formal-align \
  --gate-dir /tmp/rtl_obfuscation_t029/gate \
  --gate-view-dir /tmp/rtl_obfuscation_t029/formal-gate \
  --gate-view-manifest /tmp/rtl_obfuscation_t029/formal-gate.json \
  --map /tmp/rtl_obfuscation_t029/mapping.json \
  --output-dir /tmp/rtl_obfuscation_t029/formal-gate-aligned \
  --manifest /tmp/rtl_obfuscation_t029/formal-gate-aligned.json
```

固定处理链为：

```text
真实 1091/5741 product gate
  -> 260 项 AST-driven gate formal view
  -> 5527 个 mapping-validated identifier-only replacements
  -> 原第 13 节 Yosys equivalence flow
```

实现和验收必须满足：

1. 先使用 T028 完整 mapping v3 validator 校验 schema、selected groups/categories、1091/5741、
   product gate ranges 和 gate manifest；不得另写宽松 validator。
2. gate formal-view manifest 必须通过第 11 节完整校验，其 `source_manifest_sha256` 必须等于
   mapping 的 `gate_manifest_sha256`；top、files 和 compile order 必须全部一致。
3. 使用 `pyslang.parsing.Lexer`，只接受 `TokenKind.Identifier` 且 `rawText` 精确等于一个全局唯一
   `renamed_name` 的 token；comments、strings、directives、trivia、escaped identifiers、operators、
   literals 和其他 token 不得改变。
4. 每个 replacement 的输入 bytes 必须等于 mapping 的 `renamed_name`，输出 bytes 只能是同一
   entry 的 `original_name`；不得读取 gold root、按 gold diff 生成替换或调用 `decrypt-project`。
5. `design.f` 逐字节复制，19 个 relative files 不变；输出必须再次通过
   `read_verilog -sv -formal -defer` 和 `hierarchy -check -top vector_top`。
6. 输出目录和 manifest 事务发布；mapping、gate、gate view、manifest mismatch、非 identifier
   命中、重复/冲突名字、5527 oracle 不匹配或 Yosys failure 都退出 1且不发布。
7. aligned view 是 formal-only name-matching derivative，不是解密产品，不参与 decrypt，不得写回
   product gate、gold 或原 gate formal view。

alignment manifest v1 顶层字段必须精确为：

```json
{
  "version": 1,
  "mode": "formal-name-alignment",
  "top": "vector_top",
  "source_files": [],
  "compile_order": [],
  "source_gate_manifest_sha256": "",
  "source_view_manifest_sha256": "",
  "mapping_sha256": "",
  "mapping_entries": 1091,
  "mapping_occurrences": 5741,
  "identifier_replacements": 5527,
  "aligned_view_manifest_sha256": "",
  "design_file": "design.f"
}
```

不得记录绝对路径、时间戳、临时目录或随机 id。RISC 固定成功 stdout：

```json
{"files": 19, "identifier_replacements": 5527, "top": "vector_top", "view_manifest_sha256": "d3031e8f71891203f16fa8ff7d5022e8105f13e2237a188669d1698a7f8accc7"}
```

aligned 19-file manifest 固定为
`d3031e8f71891203f16fa8ff7d5022e8105f13e2237a188669d1698a7f8accc7`，必须不同于 gold view
manifest `56572fb2...649872`。两者唯一允许的非 token 差异来自两条 assertion blank 的空格长度；
不得把 gold files 复制到 aligned output 来满足该 hash。

## 13. Yosys formal 合同

### 13.1 `scripts/formal_equivalence.py` 最小修正

仅 multifile mode：

- gold/gate `read_verilog` 都使用 `-sv -formal -defer`；
- gold/gate 都在 `prep -top <top> -flatten` 后、`memory_map -formal` 前执行 `async2sync`；
- 其余 `opt_clean/equiv_make/equiv_struct/equiv_simple/equiv_induct/equiv_status -assert` 保持；
- single-file mode 和 JSON schema 保持兼容；
- T028 FIFO formal 必须继续通过。

### 13.2 RISC 正例

gold 输入必须是由固定原工程生成的 gold formal view；gate 输入必须是由 1091/5741 真实加密 gate
独立生成的 gate formal view，再严格经过第 12.5 节 5527-token formal alignment。禁止
gold=gate、复制 gold 充当 aligned gate、调用 `decrypt-project`、把 restored tree 送入 formal，
或只对 FIFO/子模块运行 formal。

先运行第 12.5 节固定 `formal-align` 命令，再运行：

```sh
conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold-filelist /tmp/rtl_obfuscation_t029/formal-gold/design.f \
  --gold-root /tmp/rtl_obfuscation_t029/formal-gold \
  --gate-filelist /tmp/rtl_obfuscation_t029/formal-gate-aligned/design.f \
  --gate-root /tmp/rtl_obfuscation_t029/formal-gate-aligned \
  --top vector_top \
  --seq 1
```

必须退出 0，stdout JSON 为 `formal_equivalence=pass/top=vector_top/seq=1`；Yosys 最终必须为
0 unproven。600 秒单次超时保持不变；主 Agent 固定环境实测约 162 秒。验收环境应预留至少
3 GiB 内存，不得把 timeout、OOM 或 KeyboardInterrupt 当作 pass。

### 13.3 固定功能负例

从通过的 `formal-gate-aligned` 复制 negative tree，只在
`rtl/vector/vector_top.sv` 的 `assign vector_idle_o = ...` 中，把第一个二元 `&` token 改为
`|`；测试必须先断言只改变一个 byte/token，其他文件 hash 不变。

使用相同 gold/top/seq 运行 formal，必须退出非 0，最终 `equiv_status -assert` 固定留下 1 个
未证明 cell，且名称为 `vector_idle_o`。固定 negative 19-file manifest 为
`65e5933dd66b272e924e84ec000313f51d69f9109becd49dd062e1a94fcfb7d6`。不得修改 gold、alignment
mapping、assumption、formal script 或 timeout 来制造负例；不得以 timeout 代替该明确失败。

## 14. Yosys view 警告边界

READY gold view hierarchy 探针固定存在下列源工程/Yosys 警告类别：

- `vmu_tp_eng.sv:299`：`nxt_stride` used before Yosys declaration；
- `vmu.sv:239/287/336/420`：四个 used-before-declaration implicit warnings；
- `vex_pipe.sv:128`：`microop_i[6:5]` 对 top 参数化后的 5-bit input 越界；
- 8 个 `vex_pipe.microop_i` 7→5 resize；
- 4 个 vmu response data/size resize。

归一化后共 18 个唯一 warning location/class。gold、原 gate 和 aligned gate 的归一化集合必须一致；
identifier 重命名和 `$paramod` hash 被忽略。不得新增 warning location/class，也不得静默过滤
Yosys stderr。

## 15. 错误处理和事务性

- inventory 无法唯一绑定：inspect/encrypt 退出 1，不发布成功 artifacts；
- formal-view unsupported AST shape 或 Yosys failure：退出 1，不发布 view/manifest；
- formal-align mapping/gate/view/manifest/lexer/count/hash mismatch 或 Yosys failure：退出 1，不发布
  aligned view/manifest；
- invalid CLI/path：argparse 退出 2；
- source/input/view manifest、transform range/hash 或 symmetry 失败：验收失败；
- formal 正例 timeout/nonzero 或负例返回 0：验收失败；
- stdout 只输出成功 JSON；错误写 stderr；
- 不得捕获异常后复制原 RTL、跳过对象或返回 coverage=1.0。

## 16. 子 Agent 内部执行方案

### 阶段 A：开始和基线

1. 设置 `IN_PROGRESS`，记录 HEAD/首条命令。
2. 重跑 67 项基线、T027/T028 目标测试和 FIFO formal。
3. 校验第 4 节输入 manifest、17/19 closure 和当前 1085/5378 已知起点。
4. 复现 signals-only、ports-only 和 assertion-only Yosys 三个已知失败。

阶段门禁：基线与合同一致，固定输入相对 `9386135` 无变化。

### 阶段 B：inventory 完整性

1. 修正两个 signal actual-argument ranges。
2. 修正 223 个 packed aggregate port base ranges。
3. 为 symbol identity 已匹配但 `syntax is None` 的 port NamedValue 补 104 个精确
   `sourceRange`。
4. 对 uninstantiated generate actual 使用 lexical parent lookup，补 14 个父模块 port
   references。
5. 递归识别 packed-array element alias，加入 `to_vector_exec` 1+5 对象。
6. 运行 canonical digest、五组单独 gate 和 combined gate。

阶段门禁：第 6 节全部 count/digest 精确匹配；ports-only 必须为 348/1853，combined 必须为
1091/5741；combined gate 不得出现 14 个额外 signal；gate strict compile 0/0。

### 阶段 C：formal view

1. 提取复用现有 project analysis 的最小 semantic context，不写第二套 resolver。
2. 实现第 10—12.4 节 CLI、manifest、260 项 AST-driven transforms 和事务发布。
3. 运行 gold view exact hash、重复确定性、gate symmetry 和 unsupported-shape 负例。
4. 用 `-defer` hierarchy 验证两个 view。

阶段门禁：gold view manifest 固定、gold/gate 260 项 signature 一致、Yosys hierarchy 退出 0。

### 阶段 D：formal 和端到端验收驱动

1. 最小修改 multifile formal 的 `-defer/async2sync`。
2. 实现第 12.5 节 `formal-align`，验证真实 gate、gate view 和 mapping 后生成固定
   19/5527 aligned derivative；运行确定性和事务负例。
3. 以 gold view 和 aligned gate view 运行真实 RISC 正例，再从 aligned gate view 生成固定
   `vector_idle_o` 负例。
4. 实现 `scripts/t029_acceptance.py`，一次自动完成 manifest、inspect、encrypt、gate、decrypt、
   view、symmetry、alignment、formal 正负例并输出机器 JSON。
5. 保持 FIFO formal 正负回归。

阶段门禁：alignment 为 19 files / 5527 identifier replacements / 固定 `d3031e...accc7`；RISC
正例 600 秒内退出 0/0 unproven；负例 600 秒内非 0且恰好 1 个 `vector_idle_o` unproven；
acceptance JSON status=pass。

### 阶段 E：文档和交付

1. 更新 README、重命名表、formal 文档、future work 和路线图。
2. 运行 15 项目标测试、82 项完整回归、acceptance 驱动、固定输入 diff 和 diff check。
3. 填写执行记录、偏差、formal 和交付证据。
4. 全部通过后设置 `READY_FOR_REVIEW`，不 commit/push。

## 17. 固定新增测试

新增 `tests/test_risc_v_vector_project_root.py`，正好包含以下 15 个 unittest：

```text
test_fixed_input_manifest
test_inspect_closure_compile_order_and_topology
test_inventory_exact_canonical_oracle
test_packed_array_element_struct_is_included
test_generate_local_signal_actual_arguments_are_included
test_all_semantic_port_references_are_included
test_five_group_individual_summaries
test_combined_mapping_and_metrics
test_combined_gate_strict_reinspect_and_topology
test_top_abi_and_parameters_are_preserved
test_decrypt_restores_every_closure_file
test_gold_formal_view_exact_oracle_and_determinism
test_gate_formal_view_alignment_and_symmetric_transformations
test_formal_view_rejects_unsupported_shape_transactionally
test_multifile_formal_script_keeps_fifo_compatible
```

重型 RISC formal 不放进 unittest，避免目标测试和完整 discovery 各运行一次；它必须由第 18 节
独立 acceptance 驱动执行。测试不得从加密结果反向生成 expected count/range/hash。

新增 `scripts/t029_acceptance.py`：

- 参数固定为 `--work-dir <absent-or-empty-directory>`；
- 单次执行第 4—14 节所有机器检查和 formal 正负例；
- 每次 formal timeout 600 秒；
- 成功只输出一个 JSON object，至少包含
  `status/input_manifest/closure/modules/inventory/mapping/metrics/decrypt/formal_view/`
  `formal_alignment/formal_positive/formal_negative`；
- 固定核心结果：19 files、17 modules、1091/5741、35/113、260 transforms、5527 identifier
  replacements、gold/aligned view manifests、positive pass、negative expected failure；
- 任一断言失败退出 1，不输出 `status=pass`。

## 18. 固定验收命令

### 18.1 py_compile 和目标测试

```sh
conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/project.py \
  rtl_obfuscator/inventory.py \
  rtl_obfuscator/rewrite.py \
  rtl_obfuscator/formal_view.py \
  scripts/formal_equivalence.py \
  scripts/t029_acceptance.py \
  tests/test_risc_v_vector_project_root.py

conda run -n rtl_obfuscation python -m unittest \
  tests.test_risc_v_vector_project_root -v
```

固定结果：`Ran 15 tests`、`OK`。

### 18.2 一键真实工程验收

工作目录必须预先不存在；若已存在，使用新的路径，不得由脚本删除任意用户目录。

```sh
conda run -n rtl_obfuscation python scripts/t029_acceptance.py \
  --work-dir /tmp/rtl_obfuscation_t029_acceptance
```

必须退出 0，stdout JSON 满足第 17 节；其中 formal gold、原 gate view、aligned gate view 必须是
三个不同目录；aligned manifest 必须为固定 `d3031e...accc7`，gate mapping 必须为 1091/5741。

### 18.3 独立 CLI spot checks

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite inspect-project \
  --project-root rtl_samples/RISC-V-Vector \
  --top vector_top \
  --report /tmp/rtl_obfuscation_t029_spot/gold-report.json

conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite formal-view \
  --project-root rtl_samples/RISC-V-Vector \
  --top vector_top \
  --output-dir /tmp/rtl_obfuscation_t029_spot/formal-gold \
  --manifest /tmp/rtl_obfuscation_t029_spot/formal-gold.json

conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite formal-align \
  --gate-dir /tmp/rtl_obfuscation_t029/gate \
  --gate-view-dir /tmp/rtl_obfuscation_t029/formal-gate \
  --gate-view-manifest /tmp/rtl_obfuscation_t029/formal-gate.json \
  --map /tmp/rtl_obfuscation_t029/mapping.json \
  --output-dir /tmp/rtl_obfuscation_t029_spot/formal-gate-aligned \
  --manifest /tmp/rtl_obfuscation_t029_spot/formal-gate-aligned.json
```

inspect 必须 17/19/1091/5741；formal view 必须 19/260 和固定 gold view manifest；formal-align
必须 19/5527 和固定 aligned view manifest。

### 18.4 完整回归和只读输入

```sh
conda run -n rtl_obfuscation python -m unittest discover -s tests -v
git diff --exit-code 9386135 -- tests/fixtures/t027_project_root
git diff --exit-code 9386135 -- rtl_samples/example_fifo
git diff --exit-code 9386135 -- rtl_samples/RISC-V-Vector
git diff --check
git status --short
```

固定完整回归：当前 67 项 + T029 新增 15 项 = `Ran 82 tests`、`OK`。

### 18.5 文档机器检查

```sh
rg -n "formal-view|formal-align|1091|5741|project-root.*top" \
  README.md \
  docs/systemverilog_renaming_table.md \
  docs/formal_verification.md \
  docs/future_work.md \
  docs/project_root_top_roadmap.md
```

必须全部命中文档；文档中的正式命令必须由测试或 acceptance 驱动实际执行，不能只写示例。

## 19. 主 Agent 黑盒验收

主 Agent 必须独立执行，不以代码阅读或子 Agent 日志代替：

1. 第 18.1 节 15 项测试；
2. 固定输入 manifest 和 17/19 closure；
3. eligible/preserved 完整 canonical digest；
4. 五组单独 summary 和 combined 1091/5741；
5. gate strict compile、拓扑、top ABI、parameter=0；
6. metrics 1.0/0.0；
7. 19 文件 decrypt SHA-256；
8. gold formal view 260 项、固定 manifest 和重复确定性；
9. gate formal view signature 对称；
10. formal-align 完整输入链、5527 identifier-only replacements、固定 manifest、确定性和事务负例；
11. RISC aligned-gate formal 正例和固定功能负例；
12. T028 FIFO formal 回归；
13. 82 项完整 unittest；
14. 三组固定输入 diff、允许文件、文档检查和 `git diff --check`。

任何一项失败都不得设置 `ACCEPTED`。尤其不得以 PySlang pass、decrypt pass、identity formal、
FIFO formal 或“只是重命名”代替真实 RISC gate formal。

## 20. 允许修改的文件

子 Agent 只允许修改：

```text
rtl_obfuscator/project.py                 # 仅最小复用 semantic context
rtl_obfuscator/inventory.py               # 第 3 节五项完整性修正
rtl_obfuscator/rewrite.py                 # formal-view/formal-align CLI 与 mapping v3 复用
rtl_obfuscator/formal_view.py             # formal view 和 identifier-only alignment
rtl_obfuscator/__init__.py                 # 仅公开 API 确有需要时
scripts/formal_equivalence.py              # 仅 multifile -defer/async2sync
scripts/t029_acceptance.py                 # 新文件，机器验收驱动
tests/test_risc_v_vector_project_root.py   # 新文件，正好 15 tests
README.md
docs/systemverilog_renaming_table.md
docs/formal_verification.md
docs/future_work.md
docs/project_root_top_roadmap.md
docs/tasks/T029_risc_v_vector_delivery.md
```

固定只读：

```text
rtl_samples/RISC-V-Vector/**
rtl_samples/example_fifo/**
tests/fixtures/t027_project_root/**
tests/formal/**
tests/test_*.py（除新增的 T029 文件）
docs/tasks/T001_*.md ... docs/tasks/T028_*.md
```

不得新增 dependency/lockfile、vendor 工具、生成 RTL fixture、golden gate 或提交 `/tmp` artifacts。

## 21. 严格行为规范和禁止事项

1. 不得修改 RISC、FIFO、T027 fixture 或旧测试来制造通过。
2. 不得实现 parameter/module/union_fields 或扩大五组 project-root category。
3. 不得重命名 top module、top ports 或 top ABI。
4. 不得用正则、全局文本搜索、diagnostic 文本或名字相同代替 PySlang symbol identity。
5. 不得把 compilation root 当作 selected top 树，不得另写第二套 resolver。
6. 不得漏掉 `to_vector_exec` 后仍按旧 1085/5378 计算 coverage。
7. 不得对 formal 产品 RTL做原地修改；lowering 只存在于 view output。
8. 不得删除或 blank 除两条固定 concurrent assertion 外的语句。
9. 不得用 gold=gate、`decrypt-project`/restored gate、identity copy、FIFO 或子模块 formal 冒充
   RISC gate formal；唯一允许的 name matching 是第 12.5 节经完整链路验证的 identifier-only
   `formal-align`。
10. 不得删除、弱化、捕获或绕过 `equiv_status -assert`。
11. 不得把 formal 非零、timeout、OOM 或 unsupported 描述为 pass。
12. 不得忽略负例返回 0；负例必须留下未证明 cell。
13. 不得新增 third-party dependency、网络下载、plugin 或使用 Conda base/system Python。
14. 不得放宽 mapping v3 validator、事务性或 T027/T028 oracle。
15. 不得在 acceptance 脚本删除任意既有目录；只接受不存在或空的 work dir。
16. 不得在测试中读取实现常量作为 expected oracle，或从 gate 反向生成 expected ranges。
17. 不得 commit、push、amend、rebase、reset 或删除用户变更。
18. 不得设置 `ACCEPTED`，不得创建后续任务。
19. schema、CLI、count、hash、fixture 或 formal 输入需要变化时，先记录第 23 节并停止，等待主
    Agent 修订；不得自行解释为“等价替代”。
20. `formal-align` 不得接收、读取或复制 gold root；不得修改非 `TokenKind.Identifier` token，
    不得把 gold/aligned manifest 相等、timeout 或 identity probe 当作真实 gate 正例。

## 22. 子 Agent 执行记录

开始时填写：

```text
start_time: 2026-07-17 11:15:18 CST
starting_head: fdd3aa7
first_command: `git status --short --branch && git rev-parse --short HEAD && rg -n '^- 状态：|^# T029|^## ' docs/tasks/T*.md && sed -n '1,360p' docs/tasks/README.md && sed -n '1,1100p' docs/tasks/T029*.md`
confirmed_unique_active_task: yes; T028 was ACCEPTED, T029 was the only READY task, no task was IN_PROGRESS or READY_FOR_REVIEW, and the worktree was clean
baseline_67_tests: PASS; `Ran 67 tests in 22.574s`, `OK`
t027_t028_target_tests: PASS; T027 `Ran 16 tests in 9.091s`, `OK`; T028 `Ran 18 tests in 4.752s`, `OK`
fifo_formal_baseline: PASS; exit 0 with `{"formal_equivalence":"pass","seq":5,"top":"fifo_top"}` against the accepted T028 gate
risc_input_manifest: PASS; exact `a016dd548525346508c636b97fcc452c8f6eb4fcbf930ef5eb938a2edfa2ae9d`; 56 candidates / 17 modules / 19 closure files / 0 interfaces / 0 errors; known inventory start 1085/5378; all three fixed inputs match `9386135`
risc_known_failure_reproductions: PASS; signals-only encryption exited 1 with gate eligible count mismatch; ports-only exited 1 with gate strict-analysis failure; assertion-only 19-file view exited 1 at Yosys `genrtlil.cc:1604` while deriving `vex`
phase_b: BLOCKED after the frozen inventory oracle passed exactly. `inspect-project` returned 56 candidates / 17 modules / 19 closure files / 1091 eligible symbols / 5623 eligible occurrences; canonical SHA-256 values were eligible `5c420d37665e2a922be443785fb89f0b53c6c267acb75531e883af26032a05a8`, preserved `b5b31416d834ff03eda28e28c4e625108b13e36ecdf28750dc5d78f22e244d9f`, and inventory `2c2f4d3ac25172c0458bd2fd91aab9d9132c52494fda4bfa87f85ad85070c120`. Category counts and digests also matched section 6 exactly. Group encrypt results: signals 675/3614 PASS, instances 19/19 PASS, struct 49/255 PASS, interface 0/0 PASS, ports FAILED during gate strict analysis instead of the required 348/1735 success. Per section 16, combined encryption and later phases were not run.
phase_b_resume: PASS after the 2026-07-17 contract revision. Added the authorized 104 symbol-identity `NamedValueExpression.sourceRange` fallbacks and 14 lexical-parent port actual references. `inspect-project` returned 1091/5741 and exact SHA-256 values: eligible `6d4e0ef7d46d569d2fecda8563ccdd4012eb6043cb86b9c908d06391b291e6d0`, ports `2dad5d96fdc98cc95a6285e2bfcad97fbc628e81849a9d91cf1d43a6c7a61d63`, preserved `b5b31416d834ff03eda28e28c4e625108b13e36ecdf28750dc5d78f22e244d9f`, inventory `0b661f775f936cb15ca5c39dbafbb54c450a5062a935d7daac2d16113d6b3e93`. Five group encryptions PASS: signals 675/3614, ports 348/1853, instances 19/19, struct 49/255, interface 0/0. Combined encrypt PASS at 19/1091/5741; gate strict inspect PASS at 17 modules / 19 files / 0 parse errors / 0 semantic errors / 1091/5741, with parameter entries 0. Metrics are symbol and occurrence coverage 1.0 and plaintext leakage 0.0. Decrypt PASS at 19/1091/5741; all 19 restored files are byte-identical and manifest is `a016dd548525346508c636b97fcc452c8f6eb4fcbf930ef5eb938a2edfa2ae9d`.
phase_c: PASS for implementation and direct probes. Added one shared strict `ProjectSemanticContext` path and the `formal-view` CLI. Gold generated 19 files / 260 transformations with exact kind counts 25 aggregate types + 233 packed members + 2 concurrent assertions and exact view manifest `56572fb29266c2f6cb44ef9a9846bda4585c846dc28677b9855e9bae79649872`. A second gold run produced byte-identical RTL, `design.f`, and manifest JSON. Gate generated 19/260; its complete transformation signature matched gold. Both commands passed their internal Yosys `read_verilog -sv -formal -defer` plus `hierarchy -check -top vector_top`. The two assertion ranges and source SHA-256 values matched section 12.3. A strict nested packed-array fixture exited 1 with `formal-view does not support nested packed arrays`, and neither output directory nor manifest was published.
phase_d: BLOCKED at the real RISC positive formal gate; see section 23.3. The multifile script has the authorized symmetric `-defer` and `async2sync` changes, and the T028 FIFO positive formal still passes at seq=5. No positive RISC pass, negative RISC result, or acceptance pass is claimed.
phase_d_resume: PASS after the 2026-07-17 section 23.4 authorization. Implemented mapping-v3-linked, PySlang-lexer-only `formal-align`; it changed exactly 5527 `TokenKind.Identifier` tokens from `renamed_name` to `original_name`, emitted 19 files, and produced fixed aligned manifest `d3031e8f71891203f16fa8ff7d5022e8105f13e2237a188669d1698a7f8accc7`. Repeat output/design/manifest was byte-identical; a corrupt gate-view manifest exited 1 without publishing artifacts. The original proof chain on the derived real gate passed at vector_top/seq=1 with 0 unproven. The fixed one-byte `&` to `|` mutation exited 1 with exactly one `vector_idle_o` unproven cell and manifest `65e5933dd66b272e924e84ec000313f51d69f9109becd49dd062e1a94fcfb7d6`. FIFO positive passed and its functional negative failed as required. Yosys warning lines are forwarded to CLI stderr; gold, original gate view, and aligned gate view normalize through mapping/hash/path alignment to the same fixed 18 unique location/classes.
phase_e: PASS. The complete acceptance driver exited 0 from a new `/private/tmp/rtl_obfuscation_t029_acceptance_warning_final` work directory and emitted `status=pass`. Exact py_compile passed; the 15 target tests passed in 87.136s; all 82 tests passed in 113.568s. README and the four required design/roadmap documents were updated. All three fixed inputs match `9386135`; the documentation rg check and `git diff --check` pass.
finish_time: 2026-07-17 14:59:03 CST
ending_head: fdd3aa7 (unchanged; no commit or push)
```

## 23. 偏差或阻塞

### 23.1 子 Agent 原始停点（保留审计）

```text
observed_behavior: The authorized three inventory corrections produce the exact frozen 1091/5623 inventory and every section 6 canonical digest, but a ports-only encryption still exits 1 at gate strict analysis. The staged gate has 71 `UndeclaredIdentifier` semantic errors: and_or_mux=3, vex=11, vis=24, vmu=12, vmu_ld_eng=9, vmu_st_eng=2, vmu_tp_eng=3, vrf=7. For example, and_or_mux port declarations are renamed while the module-body uses at source offsets 1074 (`sel`), 1083 (`data_in`), and 1120 (`data_out`) remain unchanged. Similarly, vex's `exec_data_i` declaration is renamed but its indexed body bases remain unchanged.
minimal_reproduction: `conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-project --project-root rtl_samples/RISC-V-Vector --top vector_top --output-dir /tmp/rtl_obfuscation_t029_phaseb_ports/gate --map /tmp/rtl_obfuscation_t029_phaseb_ports/mapping.json --metrics /tmp/rtl_obfuscation_t029_phaseb_ports/metrics.json --file-map-dir /tmp/rtl_obfuscation_t029_phaseb_ports/maps --category ports --name-length 8`; exit 1, stderr `error: gate strict project analysis failed`. Retaining the internal staging directory for diagnosis and compiling it with the same `_ProjectContext` reports the 71 errors above; the first is `rtl/shared/and_or_mux.sv:1074`.
contract_conflict: Adding the 71 semantically bound port-internal body references is necessary for a compilable ports-only (and combined) gate, but it would change the frozen ports 348/1735 digest, combined 1091/5623 digest, mapping counts, and downstream formal oracle. Section 21.19 requires stopping instead of changing those values. Omitting them satisfies every frozen inventory digest but cannot satisfy sections 6.3, 8, and 16 phase B gate strict compilation.
proposed_minimal_resolution: Main Agent should decide whether these 71 references belong to the ports occurrence oracle and revise all affected counts/digests, tests, and acceptance values. If another intended semantic representation preserves 348/1735 while producing a reversible, decryptable strict gate, that representation must be specified because the current mapping-v3 range model has no ranges for these tokens.
status: BLOCKED in phase B; task remains IN_PROGRESS. No formal-view, combined gate, formal run, documentation delivery, READY_FOR_REVIEW transition, commit, or push was performed.
```

### 23.2 主 Agent 独立复核和合同修订（2026-07-17）

主 Agent 保留工作区中的子 Agent 实现不变，只在 `/private/tmp/t029_main_oracle_repo` 副本中加入
候选最小修正并运行黑盒探针。结论：原停点有效，但 71 个 diagnostic 不是完整遗漏集合。

```text
reviewed_starting_head: fdd3aa7
reviewed_user_changes: rtl_obfuscator/inventory.py and this task contract; neither was reverted or overwritten
retained_gate_compile: PASS reproduction of 71 UndeclaredIdentifier diagnostics from the retained failed ports gate
semantic_identity_audit: 104 unique, byte-valid, previously unmapped NamedValue source ranges whose symbol is the selected port internalSymbol; 71 diagnosed plus v_int_alu=31 and vex_pipe=2 not emitted by that failed compile
source_range_fallback_probe: inspect 1091/5727; ports-only encrypt PASS at 348/1839
combined_probe_before_parent_lookup: FAIL with 1105 eligible symbols; gate added 14 one-occurrence signals at uninstantiated eb_buff_generic parent-port actuals
lexical_parent_lookup_probe: scope.find() resolves branch-local fifo_push/fifo_pop, while scope.lookupName() resolves the parent module ports; every accepted range is still gated by symbol identity
final_inspect_probe: PASS at 56 candidates / 17 modules / 19 files / 1091 eligible symbols / 5741 eligible occurrences / 0 errors
final_ports_probe: PASS at 19 files / 348 entries / 1853 modified tokens
final_combined_probe: PASS at 19 files / 1091 entries / 5741 modified tokens; gate re-inspect PASS at 17 modules / 19 files / 0 parse errors / 0 semantic errors / 1091/5741
final_combined_decrypt_probe: PASS at 19 files / 1091 entries / 5741 modified tokens; all 19 restored files byte-identical
final_eligible_sha256: 6d4e0ef7d46d569d2fecda8563ccdd4012eb6043cb86b9c908d06391b291e6d0
final_ports_sha256: 2dad5d96fdc98cc95a6285e2bfcad97fbc628e81849a9d91cf1d43a6c7a61d63
final_preserved_sha256: b5b31416d834ff03eda28e28c4e625108b13e36ecdf28750dc5d78f22e244d9f
final_inventory_sha256: 0b661f775f936cb15ca5c39dbafbb54c450a5062a935d7daac2d16113d6b3e93
formal_view_oracle_effect: product source ranges and mapping occurrence totals change; the formal-only 25 type + 233 member + 2 assertion transform oracle remains 260 because no formal-view syntax category or gold bytes changed
resolution: sections 1, 3, 6, 8, 9, 13, 16-20 and the roadmap now authorize and freeze the complete 118 additional port references
resume_authorization: sub Agent may resume Phase B from IN_PROGRESS, implement only sections 3.3.1 and 3.3.2, then rerun all Phase B digest and five-group gates against 1091/5741 before Phase C
```

该复核没有把 `/private/tmp` gate、mapping、report 或临时补丁复制回仓库，也没有执行、冒充或替代
Phase C/D 的正式 formal 验收。子 Agent 恢复后应在第 22 节增加 `phase_b_resume` 记录；原
`phase_b: BLOCKED` 行作为历史证据保留。

### 23.3 真实 gate formal 复杂度阻塞（子 Agent Phase D）

```text
observed_behavior: The required real gold/gate RISC proof did not finish within the section 17 acceptance timeout of 600 seconds. It was terminated and is not reported as pass. A second diagnostic run used the exact same Yosys command stream but redirected the otherwise captured Yosys log to `/tmp`. Elaboration, symmetric async2sync, memory_map, opt_clean, equiv_make, and equiv_struct all progressed normally. `equiv_struct -icells` converged after 249 iterations and 34738 merges, then `equiv_simple -seq 1` reported 67168 unproven `$equiv` cells in 66864 groups. A 60-second sample advanced only from 535 to 629 successful individual proofs, so this real-gate workload cannot finish inside 600 seconds with the frozen flow. The diagnostic process was terminated; no partial result is treated as success.
minimal_reproduction: `conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist /tmp/rtl_obfuscation_t029_phasec_gold1/design.f --gold-root /tmp/rtl_obfuscation_t029_phasec_gold1 --gate-filelist /tmp/rtl_obfuscation_t029_phasec_gate/design.f --gate-root /tmp/rtl_obfuscation_t029_phasec_gate --top vector_top --seq 1`; no result by approximately 600 seconds, manually interrupted with KeyboardInterrupt. FIFO command with the same modified script exited 0 and returned `formal_equivalence=pass/top=fifo_top/seq=5`.
contract_conflict: Section 3.5 freezes a READY identity observation of 35029/35029 cells and explicitly says it only proves executability, but sections 13 and 17 require a truly renamed 1091/5741 gate to finish within 600 seconds. The real gate nearly doubles the post-struct unresolved population to 67168 because the internal identifiers differ. Meeting the timeout now requires changing the formal strategy/options, adding an authorized name-alignment input, or changing the timeout; each is a contract-controlled formal input or command change forbidden to the sub Agent by sections 21.10, 21.19, and the current phase gate.
proposed_minimal_resolution: Main Agent should independently reproduce the real-gate post-`equiv_struct` counts and evaluate a sound acceleration in a temporary copy. Any allowed additional Yosys pass/option, mapping-assisted alignment, or revised resource/timeout requirement must be explicitly frozen in sections 13, 17, and 18 before the sub Agent resumes Phase D. The solution must retain `equiv_status -assert`, the functional negative, and FIFO compatibility.
status: BLOCKED in Phase D; task remains IN_PROGRESS. Phase E, RISC negative, acceptance, READY_FOR_REVIEW, commit, and push were not performed.
```

### 23.4 主 Agent formal 加速复核和合同修订（2026-07-17）

主 Agent 没有修改子 Agent 的实现，只对已保留的真实 1091/5741 gate、260-transform gold/gate
formal views 和 mapping 做 `/private/tmp` 探针。结论：不放宽 600 秒，也不改变 Yosys 证明 pass；
采用第 12.5 节 mapping-validated identifier-only alignment。

```text
reviewed_real_gate_blocker: confirmed 67168 unproven cells / 66864 groups after equiv_struct in the retained diagnostic log
rejected_probe: symmetric rename -hide + rename -enumerate without -inames remained running after 240 seconds and was terminated; not accepted
rejected_probe_with_inames: symmetric hide/enumerate plus equiv_make -inames still did not finish after 300 seconds; not accepted and not authorized
selected_probe_input: retained real gate formal view linked to the 1091/5741 mapping; no gold bytes were used to generate replacements
lexer_audit: pyslang.parsing.Lexer found exactly 5527 matches, all TokenKind.Identifier, across the 19 gate formal-view files
alignment_rule: each matched token changed only from its mapping entry renamed_name to original_name; comments, strings, trivia, directives, operators, literals, and all unmatched tokens were preserved
aligned_view_manifest: d3031e8f71891203f16fa8ff7d5022e8105f13e2237a188669d1698a7f8accc7
gold_view_manifest: 56572fb29266c2f6cb44ef9a9846bda4585c846dc28677b9855e9bae79649872
gold_copy_check: manifests differ; the only non-token byte difference after alignment is assertion-blank whitespace length in fifo_duth.sv
positive_command: original scripts/formal_equivalence.py flow, gold view versus aligned derivative of the real gate, top vector_top, seq 1
positive_result: PASS, exit 0, formal_equivalence=pass, approximately 162 seconds, equiv_status -assert with 0 unproven
negative_mutation: one byte/token only, first binary & to | in aligned rtl/vector/vector_top.sv assign vector_idle_o
negative_view_manifest: 65e5933dd66b272e924e84ec000313f51d69f9109becd49dd062e1a94fcfb7d6
negative_result: EXPECTED FAIL, exit 1, approximately 223 seconds, exactly 1 unproven cell named vector_idle_o
timeout_resolution: keep 600 seconds for each positive and negative run; timeout remains failure
formal_script_resolution: keep the authorized -defer/async2sync and original equiv_make/equiv_struct/equiv_simple/equiv_induct/equiv_status -assert sequence unchanged
contract_resolution: sections 12.5, 13, 15-21 and the roadmap now freeze formal-align CLI, manifest, 5527 count, aligned hash, positive and negative requirements
resume_authorization: sub Agent may resume Phase D from IN_PROGRESS, implement formal-align only within the revised allowed files, rerun Phase D from alignment onward, and fill phase_d_resume before Phase E
```

这些探针不构成 T029 最终 formal 交付：正式 alignment、正负例、FIFO、acceptance 和完整回归仍须由
子 Agent 运行并记录，再由主 Agent在 review 阶段独立重跑。

发现偏差时先填写并停止扩大范围：

```text
observed_behavior:
minimal_reproduction:
contract_conflict:
proposed_minimal_resolution:
status:
```

## 24. Formal verification 记录

申请 review 前必须填写：

```text
formal_verification: PASS
gold_source: rtl_samples/RISC-V-Vector
gold_view: /private/tmp/rtl_obfuscation_t029_acceptance_warning_final/formal-gold
gate_source: /private/tmp/rtl_obfuscation_t029_acceptance_warning_final/gate
gate_view: /private/tmp/rtl_obfuscation_t029_acceptance_warning_final/formal-gate-aligned
mapping: /private/tmp/rtl_obfuscation_t029_acceptance_warning_final/mapping.json
mapping_entries: 1091
mapping_occurrences: 5741
formal_alignment_manifest: /private/tmp/rtl_obfuscation_t029_acceptance_warning_final/formal-gate-aligned.json
formal_alignment_replacements: 5527 TokenKind.Identifier tokens; renamed_name -> original_name only
formal_alignment_view_manifest: d3031e8f71891203f16fa8ff7d5022e8105f13e2237a188669d1698a7f8accc7
top: vector_top
seq: 1
command: `conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist /private/tmp/rtl_obfuscation_t029_acceptance_warning_final/formal-gold/design.f --gold-root /private/tmp/rtl_obfuscation_t029_acceptance_warning_final/formal-gold --gate-filelist /private/tmp/rtl_obfuscation_t029_acceptance_warning_final/formal-gate-aligned/design.f --gate-root /private/tmp/rtl_obfuscation_t029_acceptance_warning_final/formal-gate-aligned --top vector_top --seq 1`
exit_code: 0
result_json: `{"formal_equivalence":"pass","gate":"/private/tmp/rtl_obfuscation_t029_acceptance_warning_final/formal-gate-aligned","gold":"/private/tmp/rtl_obfuscation_t029_acceptance_warning_final/formal-gold","seq":1,"top":"vector_top"}`
equiv_cells_total: 32249 post-`equiv_struct` workset
equiv_cells_proven: 32249
equiv_cells_unproven: 0
gold_view_manifest: 56572fb29266c2f6cb44ef9a9846bda4585c846dc28677b9855e9bae79649872
gate_view_manifest: 72a2e87f67b94a948853f1ab5af07a5a2c2f36ae749a877254754ed379cdcd6f before alignment; aligned view manifest is the fixed value above
view_signature_match: PASS; 260/260 structural signatures and 18/18 normalized Yosys warning location/classes match across gold, original gate, and aligned gate
negative_mutation: exactly one byte/token in aligned `rtl/vector/vector_top.sv`, first binary `&` to `|` in `assign vector_idle_o`; all other bytes unchanged; 19-file manifest `65e5933dd66b272e924e84ec000313f51d69f9109becd49dd062e1a94fcfb7d6`
negative_command: `conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist /private/tmp/rtl_obfuscation_t029_acceptance_warning_final/formal-gold/design.f --gold-root /private/tmp/rtl_obfuscation_t029_acceptance_warning_final/formal-gold --gate-filelist /private/tmp/rtl_obfuscation_t029_acceptance_warning_final/formal-gate-negative/design.f --gate-root /private/tmp/rtl_obfuscation_t029_acceptance_warning_final/formal-gate-negative --top vector_top --seq 1`
negative_exit_code: 1 (expected functional failure, not timeout)
negative_unproven: exactly 1 cell, `vector_idle_o`
fifo_regression_command: executed by `conda run -n rtl_obfuscation python scripts/t029_acceptance.py --work-dir /private/tmp/rtl_obfuscation_t029_acceptance_warning_final` using the unchanged `scripts/formal_equivalence.py` flow at fifo_top/seq=5 for both the product gate and a temporary functional mutation
fifo_regression_result: positive PASS; functional negative EXPECTED FAIL
```

只有真实 gate 正例 PASS、固定功能负例非 0、FIFO 回归 PASS 时才能设置 `READY_FOR_REVIEW`。

## 25. READY_FOR_REVIEW 交付证据

完成后填写：

```text
changed_files: `README.md`; `docs/formal_verification.md`; `docs/future_work.md`; `docs/project_root_top_roadmap.md`; `docs/systemverilog_renaming_table.md`; `docs/tasks/T029_risc_v_vector_delivery.md`; `rtl_obfuscator/inventory.py`; `rtl_obfuscator/project.py`; `rtl_obfuscator/rewrite.py`; `rtl_obfuscator/formal_view.py` (new); `scripts/formal_equivalence.py`; `scripts/t029_acceptance.py` (new); `tests/test_risc_v_vector_project_root.py` (new)
exact_commands: the section 18.1 py_compile command; `conda run -n rtl_obfuscation python -m unittest tests.test_risc_v_vector_project_root -v`; `conda run -n rtl_obfuscation python scripts/t029_acceptance.py --work-dir /private/tmp/rtl_obfuscation_t029_acceptance_warning_final`; `conda run -n rtl_obfuscation python -m unittest discover -s tests -v`; the three section 18.4 `git diff --exit-code 9386135` commands; the section 18.5 `rg` command; `git diff --check`; `git status --short`
exit_codes: all positive/inspection/compile/decrypt/acceptance/test/diff/documentation commands 0; unsupported-view, corrupt-alignment-manifest, RISC functional negative, and FIFO functional negative commands nonzero as required
input_manifest_result: PASS; `a016dd548525346508c636b97fcc452c8f6eb4fcbf930ef5eb938a2edfa2ae9d`
closure_topology_result: PASS; 56 candidates / 17 modules / 19 files / 0 interfaces / 0 parse errors / 0 semantic errors; frozen compile order and instance topology match
inventory_oracle_result: PASS; eligible 1091/5741 SHA `6d4e0ef7d46d569d2fecda8563ccdd4012eb6043cb86b9c908d06391b291e6d0`; preserved 35/113 SHA `b5b31416d834ff03eda28e28c4e625108b13e36ecdf28750dc5d78f22e244d9f`; inventory SHA `0b661f775f936cb15ca5c39dbafbb54c450a5062a935d7daac2d16113d6b3e93`
signal_reference_fix_result: PASS; generate-local fifo_push/fifo_pop actual ranges are bound and included
port_reference_fix_result: PASS; 348/1853, canonical SHA `2dad5d96fdc98cc95a6285e2bfcad97fbc628e81849a9d91cf1d43a6c7a61d63`; all 104 syntax-less and 14 lexical-parent actual references included by symbol identity
packed_array_struct_result: PASS; `to_vector_exec` and its five field families included with the frozen occurrences
group_summaries: PASS; signals 675/3614, ports 348/1853, instances 19/19, struct 49/255, interface 0/0
combined_mapping_result: PASS; 19 files / 1091 entries / 5741 tokens; mapping-v3 file/range/manifest audit passed; parameters=0
gate_reinspect_result: PASS; 17 modules / 19 files / 0 parse errors / 0 semantic errors / 1091/5741; compile order and topology unchanged
top_abi_result: PASS; top module, 11 top ports, and 24 top ABI types remain preserved; parameter entries=0
metrics_result: PASS; symbol coverage=1.0, occurrence coverage=1.0, plaintext leakage=0.0
decrypt_hash_result: PASS; 19/1091/5741 and every closure file byte-identical; restored manifest equals fixed input manifest
formal_gold_view_result: PASS; 19 files / 260 transformations = 25 aggregate + 233 member + 2 assertion; fixed manifest `56572fb29266c2f6cb44ef9a9846bda4585c846dc28677b9855e9bae79649872`
formal_gate_view_result: PASS; 19/260, all structural signatures symmetric with gold, Yosys hierarchy passes, and normalized warning set equals gold at 18 unique location/classes
formal_view_determinism_result: PASS; two gold runs and two alignment runs have byte-identical RTL, design.f, and JSON manifests
formal_view_negative_result: PASS; unsupported nested packed array exits 1 and publishes neither view nor manifest
formal_alignment_result: PASS; full gate/mapping/view chain validated, exactly 5527 lexer identifier replacements, fixed manifest `d3031e8f71891203f16fa8ff7d5022e8105f13e2237a188669d1698a7f8accc7`; invalid manifest is transactional
formal_positive_result: PASS; real gate derivative, vector_top/seq=1, exit 0, 0 unproven
formal_functional_negative_result: EXPECTED FAIL; fixed one-byte `&` to `|`, exit 1, exactly one `vector_idle_o` unproven
fifo_formal_regression_result: PASS; positive passed, temporary functional negative failed
acceptance_driver_result: PASS; exit 0; one stdout JSON object with `status=pass`, 1091/5741, 260 transformations, 18 warnings, 5527 replacements, RISC positive/negative, and FIFO positive/negative
target_unittest_result: PASS; `Ran 15 tests in 87.136s`, `OK`
full_unittest_result: PASS; `Ran 82 tests in 113.568s`, `OK`
fixed_input_diff_result: PASS; T027 fixture, FIFO, and RISC-V-Vector each match baseline `9386135`
documentation_result: PASS; README, renaming table, formal guide, future work, and roadmap document the delivered project-root flow and section 18.5 rg matches all required terms
git_diff_check: PASS; no whitespace errors; worktree contains only the 13 allowed delivery files listed above
uncovered_boundaries: unchanged contract boundaries: no parameter/module/top-ABI renaming; no Tcl/IP catalog/precompiled library/DPI/class/bind/checker/primitive/testbench/SDC/external hierarchical reference support; formal view rejects unapproved AST shapes
```

## 26. 主 Agent 独立验收结果

由主 Agent 验收时填写：

```text
accepted_at: 2026-07-17 15:20:13 CST
accepted_head_before_commit: fdd3aa7
target_unittest: PASS; `Ran 15 tests in 87.459s`, `OK`
full_unittest: PASS; `Ran 82 tests in 110.669s`, `OK`
input_manifest: PASS; 19-file manifest `a016dd548525346508c636b97fcc452c8f6eb4fcbf930ef5eb938a2edfa2ae9d`
inventory: PASS; eligible 1091/5741, preserved 35/113, all frozen canonical digests exact
encryption: PASS; combined 19 files / 1091 entries / 5741 tokens, five individual groups passed in the target suite, parameter entries 0
gate_compile: PASS; 17 modules / 19 files / 0 parse errors / 0 semantic errors, compile order and topology exact
metrics: PASS; symbol coverage 1.0, occurrence coverage 1.0, plaintext leakage 0.0
decrypt: PASS; 19 files byte-identical, restored manifest equals the fixed input manifest
formal_view: PASS; 260 transformations, 18 normalized warning classes on gold/gate/aligned, gold manifest `56572fb29266c2f6cb44ef9a9846bda4585c846dc28677b9855e9bae79649872`, alignment 5527 identifiers and manifest `d3031e8f71891203f16fa8ff7d5022e8105f13e2237a188669d1698a7f8accc7`
formal_positive: PASS; independent acceptance work dir `/private/tmp/rtl_obfuscation_t029_main_acceptance_20260717`, vector_top/seq=1, exit 0, 0 unproven
formal_negative: EXPECTED FAIL; exact one-byte `&` to `|`, fixed manifest `65e5933dd66b272e924e84ec000313f51d69f9109becd49dd062e1a94fcfb7d6`, exactly one unproven `vector_idle_o`
fifo_regression: PASS; positive pass and temporary functional negative expected-fail
fixed_inputs: PASS; T027 fixture, example FIFO and RISC-V-Vector each have zero diff from `9386135`
documentation: PASS; all five required documents satisfy the section 18.5 machine check
diff_check: PASS; py_compile and `git diff --check` exit 0; only the 13 allowed delivery files changed
decision: ACCEPTED; all section 19 black-box gates independently rerun by the Main Agent
commit: not yet performed when this acceptance record was written; Main Agent delivery follows the required ACCEPTED transition
push: not yet performed when this acceptance record was written; Main Agent delivery follows the required ACCEPTED transition
```
