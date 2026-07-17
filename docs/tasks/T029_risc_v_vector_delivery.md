# T029：RISC-V-Vector 真实工程加密与 formal-view 交付

- 状态：`READY`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T028 `ACCEPTED`
- 实现基线提交：`9386135`
- 路线图：[`docs/project_root_top_roadmap.md`](../project_root_top_roadmap.md)
- Formal verification：必须 `PASS`

## 1. 单一目标

在不修改固定样例 `rtl_samples/RISC-V-Vector/` 的前提下，让 T027/T028 的通用
`project-root + top` 能力对 `vector_top` 完成一次真实的、可审计的工程级交付：

1. 修正真实工程暴露的三类漏收 source range；
2. 对 `signals/ports/instances/struct/interface` 五组执行组合加密；
3. 严格重编译 gate，证明 17 个 reachable module、19 个 closure file 和实例拓扑不变；
4. 校验 mapping/metrics、top ABI、解密逐字节恢复和所有固定 oracle；
5. 对 gold/gate 对称生成确定性的 Yosys formal view；
6. 使用真实 gate 运行 Yosys 等价正例和功能负例；
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
0 semantic error、1085 eligible symbols、5378 eligible occurrences。前三项错误使后两个 inventory
数字不完整，本任务明确授权最小修正。

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
eligible:  1091 symbols / 5623 occurrences
eligible_sha256: 5c420d37665e2a922be443785fb89f0b53c6c267acb75531e883af26032a05a8
preserved: 35 symbols / 113 occurrences
preserved_sha256: b5b31416d834ff03eda28e28c4e625108b13e36ecdf28750dc5d78f22e244d9f
inventory_sha256: 2c2f4d3ac25172c0458bd2fd91aab9d9132c52494fda4bfa87f85ad85070c120
```

### 6.2 category oracle

| actual category | eligible symbols | eligible occurrences | eligible canonical SHA-256 | preserved symbols | preserved occurrences |
| --- | ---: | ---: | --- | ---: | ---: |
| `signals` | 675 | 3614 | `edefb29037c1f7c08eb017494ed6a12bb67948c9c86ac2077e2238504327dc1e` | 0 | 0 |
| `ports` | 348 | 1735 | `7c47ba763e2d6466684e9ae7512731e5c318f71df463c7d6ff8a9caddfcf8711` | 11 | 37 |
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
| `ports` | 348 | 1735 |
| `instances` | 19 | 19 |
| `struct` | 49 | 255 |
| `interface` | 0 | 0 |
| combined five groups | 1091 | 5623 |

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
{"files": 19, "mapping_entries": 1091, "modified_tokens": 5623}
```

必须满足 T028 mapping v3 schema、manifest、事务发布、per-file map 和 decrypt 合同；不能为 RISC
增加私有 mapping 字段或特殊 category。gate strict inspect 必须为 0/0 diagnostics、1091/5623
renamed inventory、17 modules、19 files。metrics 固定：

```text
symbols: total=1091, renamed=1091, coverage=1.0
occurrences: total=5623, renamed=5623, coverage=1.0
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

stdout 必须同样为 19/1091/5623。验收驱动必须对 mapping `files` 中每个文件比较 bytes 和
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

## 13. Yosys formal 合同

### 13.1 `scripts/formal_equivalence.py` 最小修正

仅 multifile mode：

- gold/gate `read_verilog` 都使用 `-sv -formal -defer`；
- gold/gate 都在 `prep -top <top> -flatten` 后、`memory_map -formal` 前执行 `async2sync`；
- 其余 `opt_clean/equiv_make/equiv_struct/equiv_simple/equiv_induct/equiv_status -assert` 保持；
- single-file mode 和 JSON schema 保持兼容；
- T028 FIFO formal 必须继续通过。

### 13.2 RISC 正例

gold 输入必须是由固定原工程生成的 gold formal view；gate 输入必须是由 1091/5623 真实加密 gate
独立生成的 gate formal view。禁止 gold=gate、复制 gold 充当 gate、先解密 gate 再 formal，或只
对 FIFO/子模块运行 formal。

固定命令：

```sh
conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold-filelist /tmp/rtl_obfuscation_t029/formal-gold/design.f \
  --gold-root /tmp/rtl_obfuscation_t029/formal-gold \
  --gate-filelist /tmp/rtl_obfuscation_t029/formal-gate/design.f \
  --gate-root /tmp/rtl_obfuscation_t029/formal-gate \
  --top vector_top \
  --seq 1
```

必须退出 0，stdout JSON 为 `formal_equivalence=pass/top=vector_top/seq=1`；Yosys 最终必须为
0 unproven。验收环境应预留至少 3 GiB 内存和 600 秒单次超时。

### 13.3 固定功能负例

从通过的 gate formal view 复制 negative tree，只在
`rtl/vector/vector_top.sv` 的 `assign vector_idle_o = ...` 中，把第一个二元 `&` token 改为
`|`；测试必须先断言只改变一个 byte/token，其他文件 hash 不变。

使用相同 gold/top/seq 运行 formal，必须退出非 0，最终 `equiv_status -assert` 至少留下 1 个
未证明 cell，且包含 `vector_idle_o`。不得修改 gold、assumption、formal script 或 timeout 来制造
负例。

## 14. Yosys view 警告边界

READY gold view hierarchy 探针固定存在下列源工程/Yosys 警告类别：

- `vmu_tp_eng.sv:299`：`nxt_stride` used before Yosys declaration；
- `vmu.sv:239/287/336/420`：四个 used-before-declaration implicit warnings；
- `vex_pipe.sv:128`：`microop_i[6:5]` 对 top 参数化后的 5-bit input 越界；
- 8 个 `vex_pipe.microop_i` 7→5 resize；
- 4 个 vmu response data/size resize。

归一化后共 18 个唯一 warning location/class。gold/gate 的归一化集合必须一致；identifier 重命名
和 `$paramod` hash 被忽略。不得新增 warning location/class，也不得静默过滤 Yosys stderr。

## 15. 错误处理和事务性

- inventory 无法唯一绑定：inspect/encrypt 退出 1，不发布成功 artifacts；
- formal-view unsupported AST shape 或 Yosys failure：退出 1，不发布 view/manifest；
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
3. 递归识别 packed-array element alias，加入 `to_vector_exec` 1+5 对象。
4. 运行 canonical digest、五组单独 gate 和 combined gate。

阶段门禁：第 6 节全部 count/digest 精确匹配；五组 summary 精确匹配；gate strict compile 0/0。

### 阶段 C：formal view

1. 提取复用现有 project analysis 的最小 semantic context，不写第二套 resolver。
2. 实现第 10—12 节 CLI、manifest、260 项 AST-driven transforms 和事务发布。
3. 运行 gold view exact hash、重复确定性、gate symmetry 和 unsupported-shape 负例。
4. 用 `-defer` hierarchy 验证两个 view。

阶段门禁：gold view manifest 固定、gold/gate 260 项 signature 一致、Yosys hierarchy 退出 0。

### 阶段 D：formal 和端到端验收驱动

1. 最小修改 multifile formal 的 `-defer/async2sync`。
2. 运行真实 RISC gate 正例和固定 `vector_idle_o` 负例。
3. 实现 `scripts/t029_acceptance.py`，一次自动完成 manifest、inspect、encrypt、gate、decrypt、
   view、symmetry、formal 正负例并输出机器 JSON。
4. 保持 FIFO formal 正负回归。

阶段门禁：RISC 正例退出 0/0 unproven；负例非 0/至少 1 unproven；acceptance JSON status=pass。

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
test_aggregate_port_member_bases_are_included
test_five_group_individual_summaries
test_combined_mapping_and_metrics
test_combined_gate_strict_reinspect_and_topology
test_top_abi_and_parameters_are_preserved
test_decrypt_restores_every_closure_file
test_gold_formal_view_exact_oracle_and_determinism
test_gate_formal_view_has_symmetric_transformations
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
  `formal_positive/formal_negative`；
- 固定核心结果：19 files、17 modules、1091/5623、35/113、260 transforms、
  gold view manifest、positive pass、negative expected failure；
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

必须退出 0，stdout JSON 满足第 17 节；其中 formal gold/gate 必须是不同目录、不同 source
manifest，gate mapping 必须为 1091/5623。

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
```

inspect 必须 17/19/1091/5623；formal view 必须 19/260 和固定 gold view manifest。

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
rg -n "formal-view|1091|5623|project-root.*top" \
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
4. 五组单独 summary 和 combined 1091/5623；
5. gate strict compile、拓扑、top ABI、parameter=0；
6. metrics 1.0/0.0；
7. 19 文件 decrypt SHA-256；
8. gold formal view 260 项、固定 manifest 和重复确定性；
9. gate formal view signature 对称；
10. RISC formal 正例和固定功能负例；
11. T028 FIFO formal 回归；
12. 82 项完整 unittest；
13. 三组固定输入 diff、允许文件、文档检查和 `git diff --check`。

任何一项失败都不得设置 `ACCEPTED`。尤其不得以 PySlang pass、decrypt pass、identity formal、
FIFO formal 或“只是重命名”代替真实 RISC gate formal。

## 20. 允许修改的文件

子 Agent 只允许修改：

```text
rtl_obfuscator/project.py                 # 仅最小复用 semantic context
rtl_obfuscator/inventory.py               # 第 3 节三项完整性修正
rtl_obfuscator/rewrite.py                 # formal-view CLI 接线
rtl_obfuscator/formal_view.py             # 新文件
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
9. 不得用 gold=gate、解密后的 gate、identity copy、FIFO 或子模块 formal 冒充 RISC gate formal。
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

## 22. 子 Agent 执行记录

开始时填写：

```text
start_time:
starting_head:
first_command:
confirmed_unique_active_task:
baseline_67_tests:
t027_t028_target_tests:
fifo_formal_baseline:
risc_input_manifest:
risc_known_failure_reproductions:
phase_b:
phase_c:
phase_d:
phase_e:
finish_time:
ending_head:
```

## 23. 偏差或阻塞

当前：

```text
None
```

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
formal_verification: PASS | FAIL | BLOCKED
gold_source: rtl_samples/RISC-V-Vector
gold_view:
gate_source:
gate_view:
mapping:
mapping_entries:
mapping_occurrences:
top: vector_top
seq: 1
command:
exit_code:
result_json:
equiv_cells_total:
equiv_cells_proven:
equiv_cells_unproven:
gold_view_manifest:
gate_view_manifest:
view_signature_match:
negative_mutation:
negative_command:
negative_exit_code:
negative_unproven:
fifo_regression_command:
fifo_regression_result:
```

只有真实 gate 正例 PASS、固定功能负例非 0、FIFO 回归 PASS 时才能设置 `READY_FOR_REVIEW`。

## 25. READY_FOR_REVIEW 交付证据

完成后填写：

```text
changed_files:
exact_commands:
exit_codes:
input_manifest_result:
closure_topology_result:
inventory_oracle_result:
signal_reference_fix_result:
port_reference_fix_result:
packed_array_struct_result:
group_summaries:
combined_mapping_result:
gate_reinspect_result:
top_abi_result:
metrics_result:
decrypt_hash_result:
formal_gold_view_result:
formal_gate_view_result:
formal_view_determinism_result:
formal_view_negative_result:
formal_positive_result:
formal_functional_negative_result:
fifo_formal_regression_result:
acceptance_driver_result:
target_unittest_result:
full_unittest_result:
fixed_input_diff_result:
documentation_result:
git_diff_check:
uncovered_boundaries:
```

## 26. 主 Agent 独立验收结果

由主 Agent 验收时填写：

```text
accepted_at:
accepted_head_before_commit:
target_unittest:
full_unittest:
input_manifest:
inventory:
encryption:
gate_compile:
metrics:
decrypt:
formal_view:
formal_positive:
formal_negative:
fifo_regression:
fixed_inputs:
documentation:
diff_check:
decision:
commit:
push:
```
