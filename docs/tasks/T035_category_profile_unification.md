# T035：filelist/project-root 默认与手动 category profile 统一

- 状态：ACCEPTED
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T034 ACCEPTED
- 计划文档：docs/category_profile_normalization_plan.md
- 路线图：docs/project_root_top_roadmap.md
- Formal verification：必须 PASS；另需一个故意功能变更的 FAIL 负例
- RISC-V-Vector Formal：N/A；只在专门的 RISC 验收任务中执行

## 1. 单一目标

在显式 filelist 和 project-root + top 两个多文件入口中，使用同一套 canonical category
registry、默认 profile、手动 profile、alias 展开、ownership、preserved/skipped 语义和
mapping 审计规则。

T035 不再把 filelist 的 multi/ABI 类别永久视为“只能 project-root 使用”的产品边界。
统一后的安全策略如下：

1. filelist 默认 profile 仍不建立 top closure，处理 filelist 中列出的每个 RTL 文件；
2. filelist 选择任何手动 multi/ABI category 时，使用现有必填 --top 在显式 filelist 内建立
   严格语义闭包；只要依赖缺失、top 不唯一、绑定不明确或出现未覆盖的外部层次引用，就在写
   任何 gate/mapping/metrics 前 fail-closed；
3. project-root 默认 profile 和手动 profile 使用相同的 category 解析结果，但 project-root
   仍通过自动发现 include、macro、module、interface、type 依赖来建立闭包；
4. 默认 profile 与手动 profile 的判定由共享 registry 决定，不能在 inventory.py、project.py
   和 rewrite.py 中各自维护一份模式专用列表；
5. top module、top ordinary ports、top interface ABI、top parameter 和其 ABI 类型始终
   preserved，即使用户显式选择了对应手动 category；
6. 单文件入口保持 T034 的限制：multi/ABI category 仍返回
   CATEGORY_REQUIRES_PROJECT_ROOT，T035 不把单文件伪装成多文件上下文。

## 2. 固定 category 和 profile policy

### 2.1 Canonical category registry

canonical category 必须保持以下 19 个名称和顺序：

~~~
signals
parameters
enum_values
genvars
functions
tasks
arguments
instances
generate_blocks
typedefs
struct_types
struct_fields
union_fields
modules
ports
interfaces
interface_instances
interface_ports
modports
~~~

默认 profile 的 13 个 canonical category 为：

~~~
signals parameters enum_values genvars functions tasks arguments instances
generate_blocks typedefs struct_types struct_fields union_fields
~~~

默认 profile 的 eligibility 不是按 category 名字盲选，而是逐 entry 检查：

~~~
impact == single_module && abi == internal
~~~

因此 parameters 可以出现在默认 profile 的 category 列表中，但 top parameter、named
override、跨 module 参数 RHS/引用和其他 top_abi/multi_module entry 必须进入 preserved
或 skipped，不能被默认改写。

手动 profile 可选择默认 category 和以下 6 个 multi/ABI category：

~~~
modules ports interfaces interface_instances interface_ports modports
~~~

共享 compilation-unit type、跨 module parameter override、跨 module aggregate field、
有完整语义绑定的跨 module instance 也属于手动 profile 范围，即使其底层 category 是
parameters、struct_types、struct_fields、union_fields 或 instances。

### 2.2 CLI 解析规则

所有多文件入口必须接受：

- all：只展开 13 个默认 canonical category；
- 19 个 canonical category 名称；
- struct alias：展开 struct_types + struct_fields；
- interface alias：展开 interfaces + interface_instances + interface_ports + modports。

解析器必须先去重、再按 registry 顺序生成 selected_categories。同一个 physical range
只能归属一个 category，不能因为用户同时选择 ports 和 interface_ports 而产生重复 edit。

profile 解析规则：

| 请求 | profile | 范围 |
|---|---|---|
| 省略 category 或只选择默认 category/all | single_module | 默认 eligibility；filelist 为所有列出文件，project-root 为 top closure |
| 至少选择一个 6 类 multi/ABI category、struct/interface alias，或与其混选 | manual | 只在严格确认的 top context/closure 内改写 |
| 单文件选择任意 multi/ABI category | 拒绝 | CATEGORY_REQUIRES_PROJECT_ROOT |

all + ports 等混合选择在 T035 中不再作为“类别冲突”拒绝，而解析为 manual profile：
所有所选类别均限制在已确认的 top closure 内，并在 mapping 中记录 profile 和 scope policy。

### 2.3 默认行为统一

以下调用必须产生相同的 selected_categories 和 profile 语义：

~~~
encrypt-project --filelist ... --top t033_top --category all
encrypt-project --project-root ... --top t033_top --category all
encrypt-project --project-root ... --top t033_top
~~~

两种入口的文件范围仍不同，这是输入模型差异，不是 category 语义差异：

- filelist 默认：镜像并分析 filelist 列出的全部 .sv，即使某个 module 不在 top closure；
- project-root 默认：只镜像和分析自动发现的 top closure；不可达 module 不得改写。

### 2.4 手动行为统一

filelist 和 project-root 对同一组手动 category 必须使用同一 canonical entry、range、
ownership 和 rename 规则。区别仅在 closure 来源：

- filelist：只使用 filelist 提供的文件建立严格 compilation 和 top closure，不自动读取
  filelist 外文件；
- project-root：从 project root 自动发现并验证 closure；
- 两者都必须保留 top ABI，并且对缺失、歧义和外部引用 fail-closed；
- 手动 profile 成功后，未进入 top closure 的 filelist 文件仍可被镜像，但其手动 category
  entry 不得改写，并必须记录 skipped reason out_of_top_closure；
- 默认 profile 的 filelist 全文件行为只对默认 profile 保持，不可被手动 profile 隐式继承。

## 3. 固定输入与 oracle

### 3.1 分类和 profile fixture

复用 T033 已验收、不得修改的 fixture：

~~~
tests/fixtures/t033_impact_category/
├── design.f
├── bus_if.sv
├── shared.sv
├── child.sv
├── top.sv
└── decoy.sv
~~~

固定 filelist 顺序：

~~~
bus_if.sv
shared.sv
child.sv
top.sv
decoy.sv
~~~

固定 top：t033_top。

T033 fixture manifest 必须保持：

~~~
manifest: 07ca8b3be018cabfc14ce118791c7a8db8cbcb0618d3d243ad413de6c5e0aeea
candidate_files=5
closure_files=4
reachable_modules=t033_child,t033_top
reachable_interfaces=t033_bus_if
~~~

实现前必须重新核对并在执行记录中写出实际 manifest；上面的摘要不得替代真实 SHA-256
文件清单。T035 不得修改该 fixture 或 T033 的历史 oracle。

如需要新语法，只能新增 tests/fixtures/t035_profile_unification/，并在本任务执行前记录
每个文件 SHA-256 和 manifest。新 fixture 必须覆盖：

- filelist 中存在但不在 top closure 的 decoy module；
- child module parameter 被 top named override；
- child module ordinary ports 和 named connections；
- module instance name、module definition name；
- interface definition、interface instance、interface port、modport；
- module-local signal、enum、function/task/argument、generate、typedef、struct/union field；
- top module/port/interface/parameter ABI preservation；
- include/macro 产生的无法定位 physical token；
- 缺失依赖和外部 hierarchical reference 的 fail-closed 负例。

### 3.2 Default profile oracle

project-root --category all 和 project-root 省略 category 必须：

- selected_categories 精确为 13 个 default canonical category；
- 输出只包含 T033 closure 的 4 个文件；
- T033 default oracle 保持 25 symbols / 46 occurrences；
- decoy.sv 不进入 closure、mapping entries 或 gate edits；
- top module、top ordinary ports、top parameter 和 top ABI 类型进入 preserved；
- gate 重新 inspect 的 eligible ranges 与 gold mapping 一一对应。

filelist --category all 必须：

- selected_categories 与 project-root 完全一致；
- 输出和 mapping files 精确覆盖 filelist 的 5 个文件；
- T033 closure 中的 default oracle 不变；
- decoy.sv 的内部 default-eligible symbol 按 filelist 默认全文件规则改写；
- 不得因为 filelist 没有 closure 而改写 top ABI 或 multi-module range。

### 3.3 Manual profile oracle

在 T033 fixture 上选择以下 canonical categories：

~~~
modules ports interfaces interface_instances interface_ports modports
parameters struct_types struct_fields union_fields instances
~~~

filelist 和 project-root 两种入口都必须输出相同的 closure 内 manual entry oracle。以下
12 symbols / 38 occurrences 是 manual_multi_module 子集；如果同时选择 all/default
categories，mapping 还必须包含 closure 内 default eligible 子集，不能把两个 profile 子集
混成一份或漏掉任一类：

- 12 symbols / 38 occurrences 的 T033 manual_multi_module 对象必须可被改写；
- top ABI 的 4 symbols / 12 occurrences 必须 preserved，不能生成 rename edit；
- decoy.sv 必须被镜像但不得产生 manual edit，并记录 out_of_top_closure；
- modules/t033_child、child ordinary ports、interface definition/port/member/modport、
  child WIDTH named override、shared $unit type/fields 必须保持 category ownership；
- ports 不得重复收集 interface port；interface_ports 不得重复收集普通 module port；
- instances、modules、parameters 的跨 module references 必须在 gate 中全部可解析；
- mapping normalized entries（去除随机 renamed name）在 filelist 和 project-root 闭包内
  必须一致；
- aliases struct/interface 与对应 canonical category 组合必须产生相同 normalized
  category set 和相同 range oracle。
- 选择本节完整 category 列表时，T033 fixture 的 normalized mapping 必须等于
  default_profile 子集（25 symbols / 46 occurrences）与 manual_multi_module 子集（12 symbols /
  38 occurrences）的不重叠并集，即 37 symbols / 84 occurrences；top ABI 和 unsupported
  对象不计入 entries。

### 3.4 Mixed profile oracle

all + ports、all + interface 和重复 category 选择必须：

- 解析为 profile=manual；
- canonical category 去重；
- 不产生 overlapping ranges 或 duplicate mapping entries；
- filelist 和 project-root 都只改写 top closure；
- default-only filelist 的全文件行为不得被混合 profile 误用。

## 4. Category-specific implementation requirements

### 4.1 modules

- 可改写非 top module definition name；
- 同步改写 closure/filelist 内已绑定的 module instance type references；
- top module name 始终 preserved；
- 未解析的 external module、primitive、checker 或 blackbox 不得猜测改写；
- module array、hierarchical module name 和无法唯一绑定的 name 必须 preserved/unsupported。

### 4.2 ports

- 可改写非 top module ordinary port declaration；
- 同步改写已绑定的 named connection、port reference 和相关 source ranges；
- top ordinary port 始终 preserved；
- interface port 不得落入 ports ownership；
- positional connection 在无法确认绑定时 fail-closed。

### 4.3 interfaces、interface_instances、interface_ports、modports

- 只改写严格语义绑定且不属于 top ABI 的对象；
- interface definition、instance、port、modport declaration 和已绑定 references 必须
  category disjoint；
- top interface、top interface instance、top interface port、top modport/member ABI 始终
  preserved；
- modport qualified reference、interface member reference、type selector、import/export
  不能完整绑定时 preserved/unsupported；
- 不通过纯文本替换扩大 interface ABI 范围。

### 4.4 parameters

- 默认 profile 只改写 T033 classification 标为 single_module/internal 的 module value
  parameter/localparam；
- 手动 profile 可改写 closure 内 child parameter 和 named override；
- top parameter 始终 preserved；
- type parameter、package/class/interface parameter、defparam、复杂 hierarchical
  parameter、parameter array/string/real/struct 继续 fail-closed；
- parameter declaration、dimension、generate condition、named override 左侧和已绑定 RHS
  必须由同一 entry 完整覆盖，不得只改声明。

### 4.5 默认 13 类

signals、enum_values、genvars、functions、tasks、arguments、instances、
generate_blocks、typedefs、struct_types、struct_fields、union_fields 必须沿用 T033
ownership 和范围 oracle，只改变 profile 选择、closure 策略和 mapping 输出。

## 5. Mapping v4 与事务语义

T035 引入 mapping v4；v1/v2/v3 只读解密兼容必须继续通过，不得回写旧 mapping 为 v4。

最小 v4 顶层 schema：

~~~
{
  "version": 4,
  "mode": "filelist | project-root",
  "profile": "single_module | manual",
  "top": "top_module",
  "requested_categories": [],
  "selected_categories": [],
  "files": [],
  "source_files": [],
  "header_files": [],
  "closure": {},
  "compile_context": {},
  "entries": [],
  "preserved": [],
  "skipped": [],
  "name_length": 8,
  "input_manifest_sha256": "...",
  "gate_manifest_sha256": "..."
}
~~~

要求：

- requested_categories 保留用户输入顺序；selected_categories 使用 registry canonical 顺序；
- entries、preserved、skipped 都必须有稳定排序和精确 source range；
- skipped 至少支持 out_of_top_closure、top_abi、macro_expansion、unsupported、
  unresolved_external、ambiguous_binding；
- manual filelist 的 closure 明确标记为 filelist_bounded，project-root 标记为
  project_discovered；
- mapping range 必须覆盖 gold 中的原名称，gate audit 必须验证改名后范围、scope、category、
  occurrence count、closure 和 preserved/skipped 清单；
- gate、mapping、metrics、per-file maps 必须采用 staging + atomic publish；任何解析、绑定、
  range overlap、gate reanalysis 或审计失败都不得留下半成品；
- 新 mapping normalized digest 去除 renamed_name 后，重复运行必须完全一致；
- decrypt-project 必须根据 mapping v4 的 mode 正确恢复 filelist/project-root 两种 gate 的
  每个输出字节。

## 6. 实现阶段与阶段门禁

### Phase 0：启动和影响面冻结

子 Agent 开始前必须：

1. 阅读 AGENTS.md、docs/tasks/README.md、T033、T034、category normalization plan、
   formal policy 和本合同；
2. 确认没有其他 IN_PROGRESS 或 READY_FOR_REVIEW 任务；
3. 将本文件改为 IN_PROGRESS，记录 HEAD、开始时间、首条命令、fixture manifest；
4. 运行现有非 RISC 定向回归，记录 T034 后基线；
5. 列出所有因 T034 fail-closed 而变成 stale 的 filelist historical assertion，必须在执行
   记录中一次性授权，不得遇到一个失败再停一次。

### Phase 1：共享 profile resolver

- 将 canonical category、default/manual set、alias、profile resolution 和 category ownership
  收敛到一个共享实现；
- inventory.py、project.py、rewrite.py 和 CLI parser 只能调用 resolver；
- 保留 T033 classification report 和 v1/v2/v3 mapping 读取兼容；
- 为 invalid category、single-file manual、mixed selection、duplicate range 增加稳定错误码。

阶段门禁：registry unit/black-box tests、canonical order、alias expansion、profile matrix
和 no-duplicate ownership 全部通过。

### Phase 2：filelist bounded manual context

- 默认 profile 保持 T034 的 filelist 全文件行为；
- manual profile 使用显式 filelist + --top 建立 bounded closure；
- strict compilation 必须使用 filelist 明确列出的文件和同一 include/define context；
- missing dependency、ambiguous definition、unresolved module/interface、external hierarchy
  和 incomplete closure 必须在输出前失败；
- closure 外文件只镜像不改写，按 skipped 记录；
- 不得自动扫描 source-root 以弥补 filelist 缺失。

阶段门禁：T033 filelist default、manual 6 ABI category、mixed profile、decoy、missing-file
和 ambiguous-top black-box tests。

### Phase 3：project-root profile migration

- project-root 默认无 category 和 --category all 改为共享 13 类 default profile；
- project-root 接受 canonical bottom-level categories，同时保留 struct/interface alias；
- project-root manual profile 支持 19 类 registry 的合法组合；
- 保留 top ABI、closure exclusion、macro/generated-token preserved 和 existing include/define；
- legacy five-group defaults 只作为已验收历史事实迁移测试，不再作为当前默认 API；
- inspect-project、formal-view 和 encrypt/decrypt 使用同一 selected category 语义。

阶段门禁：project-root default/manual/alias/mixed、top ABI、unreachable decoy、parameter
override、gate reanalysis 和 decrypt tests。

### Phase 4：mapping v4、gate audit 和 backward compatibility

- 建立 v4 mapping 和 metrics schema；
- 让 filelist/project-root 共用 mapping entry/range/preserved/skipped validator；
- 保持 v1/v2/v3 decrypt regression；
- 对 gate 重新 inventory，校验 scope、category、range、closure、manifest、preserved/skipped；
- 检查 output transaction，失败时无 gate/mapping/metrics/file-map 残留。

阶段门禁：mapping determinism、per-file map、byte identity decrypt、transactional failure 和
legacy mapping tests。

### Phase 5：Formal、工具链和文档

- 对非 RISC formal fixture 运行真实 gate 的 Yosys positive/negative；
- 对 rich interface fixture 使用 Verible 和 PySlang 语义检查；
- 对 formal-safe module/parameter/port fixture 使用 Verible、Icarus 和 Yosys；
- 更新 README、canonical renaming table、normalization plan、roadmap 和 future work，使其
  反映 T035 实际行为；
- 不运行 tests.test_risc_v_vector_project_root，也不运行 RISC formal-view/formal-align/Yosys。

## 7. 允许修改范围

### 允许修改

- rtl_obfuscator/inventory.py
- rtl_obfuscator/project.py
- rtl_obfuscator/rewrite.py
- 如确有必要，仅允许新增一个小型共享模块：rtl_obfuscator/category_profile.py
- tests/test_t035_profile_unification.py
- 直接覆盖旧 filelist/project-root category 行为的测试：
  tests/test_example_fifo_project.py
  tests/test_formal_equivalence.py
  tests/test_module_port_rewrite.py
  tests/test_interface_rewrite.py
  tests/test_interface_member_rewrite.py
  tests/test_project_regression.py
  tests/test_project_root_low_risk.py
  tests/test_project_root_parameter_rewrite.py
  tests/test_project_root_parameters.py
  tests/test_project_root_rewrite.py
  tests/test_project_root_inspect.py
  tests/test_debug_mode.py
  tests/test_parameter_dimension_rewrite.py
  tests/test_t034_single_file_default_profile.py
- 新增的 T035 fixture 及 formal-safe fixture；不得修改 T033/T034、FIFO 或 RISC-V-Vector fixture
- README.md
- docs/systemverilog_renaming_table.md
- docs/category_profile_normalization_plan.md
- docs/project_root_top_roadmap.md
- docs/future_work.md
- 本任务单的执行记录

历史测试只允许更新其过时的 profile/category expectation，不得通过删除测试、放宽断言、跳过
测试或修改无关产品行为来制造通过结果。

### 禁止修改

- scripts/formal_equivalence.py
- 既有 v1/v2/v3 mapping validator 的向后兼容路径
- T001–T034 已验收任务单的历史执行证据
- tests/test_risc_v_vector_project_root.py 及 RISC-V-Vector RTL、Formal fixture
- 任何不属于 T035 category/profile/mapping/closure 影响面的 RTL fixture
- 不得 commit、push 或设置 ACCEPTED

## 8. 验收命令

所有 Python、PySlang、Verible、Icarus、Yosys 和测试命令必须经由
conda run -n rtl_obfuscation 执行。

### 8.1 编译和专项测试

~~~
conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/inventory.py \
  rtl_obfuscator/project.py \
  rtl_obfuscator/rewrite.py \
  rtl_obfuscator/category_profile.py \
  tests/test_t035_profile_unification.py

conda run -n rtl_obfuscation python -m unittest \
  tests.test_t035_profile_unification \
  tests.test_t033_impact_category \
  tests.test_example_fifo_project \
  tests.test_formal_equivalence \
  tests.test_module_port_rewrite \
  tests.test_interface_rewrite \
  tests.test_interface_member_rewrite \
  tests.test_project_regression \
  tests.test_project_root_low_risk \
  tests.test_project_root_parameter_rewrite \
  tests.test_project_root_rewrite \
  tests.test_project_root_inspect -v
~~~

如果 category_profile.py 最终不新增，验收命令必须删除该路径，不能把不存在的文件作为
通过条件。

### 8.2 非 RISC 常规全量回归

必须显式排除 tests.test_risc_v_vector_project_root：

~~~
conda run -n rtl_obfuscation python -m unittest \
  tests.test_all_category_rewrite \
  tests.test_debug_mode \
  tests.test_enum_value_rewrite \
  tests.test_example_fifo_project \
  tests.test_formal_equivalence \
  tests.test_genvar_rewrite \
  tests.test_hierarchy_name_rewrite \
  tests.test_interface_member_rewrite \
  tests.test_interface_rewrite \
  tests.test_localparam_rewrite \
  tests.test_module_port_rewrite \
  tests.test_multi_signal_rewrite \
  tests.test_multifile_project \
  tests.test_parameter_dimension_rewrite \
  tests.test_project_regression \
  tests.test_project_root_inspect \
  tests.test_project_root_low_risk \
  tests.test_project_root_parameter_rewrite \
  tests.test_project_root_parameters \
  tests.test_project_root_rewrite \
  tests.test_signal_net_rewrite \
  tests.test_struct_field_rewrite \
  tests.test_struct_type_rewrite \
  tests.test_subroutine_rewrite \
  tests.test_supported_integration \
  tests.test_t033_impact_category \
  tests.test_t034_single_file_default_profile \
  tests.test_t035_profile_unification \
  tests.test_typedef_rewrite \
  tests.test_union_field_rewrite \
  tests.test_value_parameter_rewrite \
  tests.test_variable_inventory \
  tests.test_variable_ranges \
  tests.test_variable_rewrite -v
~~~

### 8.3 Fixture/toolchain checks

~~~
for f in tests/fixtures/t033_impact_category/*.sv; do
  conda run -n rtl_obfuscation verible-verilog-syntax "$f"
done

conda run -n rtl_obfuscation iverilog -g2012 -t null \
  tests/formal/t032_project_root_parameters/child.sv \
  tests/formal/t032_project_root_parameters/top.sv

git diff --check
~~~

rich interface fixture 的 Icarus 限制必须单独记录；它不能替代 PySlang/Verible 语义证据，
也不能成为跳过 module/parameter/port formal 的理由。

### 8.4 Formal positive/negative

使用真实 T035 filelist manual gate，至少选择：

~~~
modules ports parameters instances
~~~

Formal-safe gold：

~~~
tests/formal/t032_project_root_parameters/design.f
top=t032_top
~~~

生成 gate 后运行：

~~~
conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold-filelist tests/formal/t032_project_root_parameters/design.f \
  --gold-root tests/formal/t032_project_root_parameters \
  --gate-filelist <temporary-gate>/design.f \
  --gate-root <temporary-gate> \
  --top t032_top
~~~

正例必须退出 0 并输出 {"formal_equivalence":"pass",...}。负例必须从真实 gate 复制，只修改
一个保持语法有效但功能不同的表达式；必须非零退出并到达 equiv_status -assert，不能以
parse、hierarchy、top 缺失或未执行证明作为“负例通过”。

### 8.5 Backward compatibility

必须通过：

- 单文件 mapping v1 decrypt；
- filelist mapping v2 decrypt；
- project-root mapping v3 decrypt；
- T030/T032 既有非 RISC fixture 的 byte-identical decrypt；
- 新 mapping v4 的 filelist/project-root decrypt；
- normalized mapping determinism、per-file maps、metrics coverage 和 zero plaintext leakage。

## 9. READY_FOR_REVIEW 门禁

子 Agent 只有在以下条件全部满足后才可设置 READY_FOR_REVIEW：

1. 本文件先从 READY 改为 IN_PROGRESS，并记录 HEAD、fixture manifest、首条命令；
2. filelist/project-root 使用同一 registry，default/manual/alias/mixed profile 全部通过；
3. 默认 profile 在两个入口的 canonical category set 完全一致；
4. manual multi/ABI profile 在两个入口都能处理 closure 内对象；
5. filelist 缺失依赖、ambiguous top、external hierarchy 和 out-of-closure 行为都有黑盒断言；
6. top module、top ports、top parameter、top interface ABI 始终 preserved；
7. no duplicate/overlap ranges，mapping v4 gate audit 和 transactional publish 通过；
8. v1/v2/v3 decrypt 回归通过，新 v4 decrypt 字节完全恢复；
9. 非 RISC 专项测试、显式排除 RISC 的全量回归、py_compile、Verible、Icarus、Formal
   正例/负例和 git diff --check 全部通过；
10. README、category table、normalization plan、roadmap 和 future work 已同步；
11. 执行记录包含 changed files、exact commands、exit codes、mapping/schema 变更、Formal
    gold/gate/top/JSON、已覆盖和未覆盖边界；
12. 不得 commit、push 或设置 ACCEPTED。

任何无法确认 owner、parameter binding、interface/member ownership、外部层次引用或
filelist closure 的情况，必须进入 preserved/skipped 或稳定错误，而不是通过名称猜测。

## 10. 执行记录

子 Agent 开始后填写：

~~~
start_time: 2026-07-21 10:21:43 CST
head: 44478a1
first_command: `sed -n '1,420p' docs/tasks/T035_category_profile_unification.md`
inherited_worktree: T034 is ACCEPTED at HEAD 44478a1; no other task is IN_PROGRESS or READY_FOR_REVIEW; existing unstaged documentation changes in `docs/category_profile_normalization_plan.md` and `docs/project_root_top_roadmap.md` are inherited and will be preserved.
fixture_manifest: candidate `.sv` manifest `07ca8b3be018cabfc14ce118791c7a8db8cbcb0618d3d243ad413de6c5e0aeea`; closure manifest `e9bca1f5787aadfe515f0b06ecb54149f536dd4ca0e6297dab1f142aea9baf9a`; candidate_files=5; closure_files=4; reachable modules=`t033_child,t033_top`; reachable interface=`t033_bus_if`; fixture file SHA-256 values match T033 contract.
changed_files: |
  rtl_obfuscator/category_profile.py
  rtl_obfuscator/inventory.py
  rtl_obfuscator/project.py
  rtl_obfuscator/rewrite.py
  tests/test_t035_profile_unification.py
  tests/test_debug_mode.py
  tests/test_example_fifo_project.py
  tests/test_formal_equivalence.py
  tests/test_interface_member_rewrite.py
  tests/test_interface_rewrite.py
  tests/test_module_port_rewrite.py
  tests/test_parameter_dimension_rewrite.py
  tests/test_project_root_inspect.py
  tests/test_project_root_low_risk.py
  tests/test_project_root_parameter_rewrite.py
  tests/test_project_root_parameters.py
  tests/test_project_root_rewrite.py
  tests/test_t034_single_file_default_profile.py
  README.md
  docs/systemverilog_renaming_table.md
  docs/category_profile_normalization_plan.md
  docs/project_root_top_roadmap.md
  docs/future_work.md
  docs/tasks/T035_category_profile_unification.md
exact_commands: |
  conda run -n rtl_obfuscation python -m unittest tests.test_all_category_rewrite tests.test_debug_mode tests.test_enum_value_rewrite tests.test_example_fifo_project tests.test_formal_equivalence tests.test_genvar_rewrite tests.test_hierarchy_name_rewrite tests.test_interface_member_rewrite tests.test_interface_rewrite tests.test_localparam_rewrite tests.test_module_port_rewrite tests.test_multi_signal_rewrite tests.test_multifile_project tests.test_parameter_dimension_rewrite tests.test_project_regression tests.test_project_root_inspect tests.test_project_root_low_risk tests.test_project_root_parameter_rewrite tests.test_project_root_parameters tests.test_project_root_rewrite tests.test_signal_net_rewrite tests.test_struct_field_rewrite tests.test_struct_type_rewrite tests.test_subroutine_rewrite tests.test_supported_integration tests.test_t033_impact_category tests.test_t034_single_file_default_profile tests.test_t035_profile_unification tests.test_typedef_rewrite tests.test_union_field_rewrite tests.test_value_parameter_rewrite tests.test_variable_inventory tests.test_variable_ranges tests.test_variable_rewrite -v
  conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/inventory.py rtl_obfuscator/project.py rtl_obfuscator/rewrite.py rtl_obfuscator/category_profile.py tests/test_t035_profile_unification.py
  for f in tests/fixtures/t033_impact_category/*.sv; do conda run -n rtl_obfuscation verible-verilog-syntax "$f" || exit 1; done
  conda run -n rtl_obfuscation iverilog -g2012 -t null tests/formal/t032_project_root_parameters/child.sv tests/formal/t032_project_root_parameters/top.sv
  git diff --check
  conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-project --filelist tests/formal/t032_project_root_parameters/design.f --source-root tests/formal/t032_project_root_parameters --top t032_top --output-dir /private/tmp/t035-formal-final-sonDZD/gate --map /private/tmp/t035-formal-final-sonDZD/mapping.json --metrics /private/tmp/t035-formal-final-sonDZD/metrics.json --name-length 8 --category modules --category ports --category parameters --category instances
  conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist tests/formal/t032_project_root_parameters/design.f --gold-root tests/formal/t032_project_root_parameters --gate-filelist /private/tmp/t035-formal-final-sonDZD/gate/design.f --gate-root /private/tmp/t035-formal-final-sonDZD/gate --top t032_top
  same formal_equivalence.py command after apply_patch changed only gate/top.sv `assign data_o = child_data;` to `assign data_o = ~child_data;`
exit_codes: |
  final explicit non-RISC unittest: 0 (`Ran 106 tests`, `OK`)
  py_compile: 0; Verible fixture loop: 0; Icarus: 0 (known constant-select warning); git diff --check: 0
  T035 manual gate generation: 0; Formal positive: 0; intentional functional negative: 1 as required
profile_matrix_summary: |
  Shared registry is the exact 19-category canonical order; default/all resolves to the exact 13-category set in both multi-file modes. Single-file multi/ABI selection remains CATEGORY_REQUIRES_PROJECT_ROOT. struct/interface aliases force manual profile and actual alias output normalized to the canonical output.
  T033 filelist default: 5 files, v2 mapping, 30 entries / 64 occurrences including decoy default-eligible symbols. T033 project-root default: 4-file discovered closure, v3 mapping, 25 entries / 46 occurrences, decoy excluded. FIFO filelist default remains 44 entries / 170 occurrences.
  Full manual canonical profile: filelist and project-root both v4, normalized closure entries 37 symbols / 84 occurrences, top ABI 4 symbols / 12 occurrences preserved; filelist policy filelist_bounded with decoy skipped as out_of_top_closure, project policy project_discovered.
mapping_v4_summary: |
  v4 records mode/profile/top/requested_categories/selected_categories/files/source_files/header_files/closure/compile_context/entries/preserved/skipped/name_length/input_manifest_sha256/gate_manifest_sha256. Entries, preserved and skipped are stable and range-disjoint; gate reanalysis validates closure, renamed bytes, preserved bytes and manifests. Manual filelist/project-root outputs and per-file maps are staged and atomically published; default v2 filelist output now uses the same staging/publish path.
legacy_decrypt_summary: |
  v1 single-file, v2 filelist and v3 project-root decrypt regressions passed in the final 106-test run. T030/T032 byte-identical decrypt, v4 filelist/project-root decrypt, normalized determinism, per-file coverage, metrics coverage=1.0 and plaintext_leakage_rate=0.0 all passed.
formal_verification: PASS
gold: tests/formal/t032_project_root_parameters/design.f (gold-root tests/formal/t032_project_root_parameters)
gate: /private/tmp/t035-formal-final-sonDZD/gate/design.f (gate-root /private/tmp/t035-formal-final-sonDZD/gate)
top: t032_top
formal_command: `conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist tests/formal/t032_project_root_parameters/design.f --gold-root tests/formal/t032_project_root_parameters --gate-filelist /private/tmp/t035-formal-final-sonDZD/gate/design.f --gate-root /private/tmp/t035-formal-final-sonDZD/gate --top t032_top`
formal_exit_code: 0 positive; 1 intentional functional negative
formal_result: `{"formal_equivalence":"pass","gate":"/private/tmp/t035-formal-final-sonDZD/gate","gold":"tests/formal/t032_project_root_parameters","seq":5,"top":"t032_top"}`
negative_formal_result: gate-only `assign data_o = ~child_data;` remained syntactically valid; command exited 1 after `equiv_status -assert` with 8 unproven `$equiv` cells, not a parse/hierarchy/top failure.
uncovered_boundaries: |
  RISC-V-Vector Formal-view/formal-align/Yosys was not run by contract; only its closure inspect regression was run. Top interface ABI is preserved rather than renamed. Missing external hierarchy was covered by a filelist fail-closed black-box test. Unsupported type/package/class/interface/$unit parameters, complex aggregate/shadowing, external blackboxes/primitive/checker/bind remain preserved/skipped or stable fail-closed.
review_request: All T035 implementation and acceptance gates are complete; status was READY_FOR_REVIEW before Main Agent acceptance. No commit or push was performed before acceptance.
scope_authorization_update: Main Agent reviewed the four directly affected expectation files tests/test_debug_mode.py, tests/test_parameter_dimension_rewrite.py, tests/test_project_root_parameters.py, and tests/test_t034_single_file_default_profile.py; their profile-migration-only changes are explicitly authorized under this contract before acceptance.
~~~

## 11. 主 Agent 验收记录

~~~
acceptance_time: 2026-07-21 11:48:32 CST
acceptance_head: 44478a1
independent_commands: |
  conda run -n rtl_obfuscation python -m unittest tests.test_all_category_rewrite tests.test_debug_mode tests.test_enum_value_rewrite tests.test_example_fifo_project tests.test_formal_equivalence tests.test_genvar_rewrite tests.test_hierarchy_name_rewrite tests.test_interface_member_rewrite tests.test_interface_rewrite tests.test_localparam_rewrite tests.test_module_port_rewrite tests.test_multi_signal_rewrite tests.test_multifile_project tests.test_parameter_dimension_rewrite tests.test_project_regression tests.test_project_root_inspect tests.test_project_root_low_risk tests.test_project_root_parameter_rewrite tests.test_project_root_parameters tests.test_project_root_rewrite tests.test_signal_net_rewrite tests.test_struct_field_rewrite tests.test_struct_type_rewrite tests.test_subroutine_rewrite tests.test_supported_integration tests.test_t033_impact_category tests.test_t034_single_file_default_profile tests.test_t035_profile_unification tests.test_typedef_rewrite tests.test_union_field_rewrite tests.test_value_parameter_rewrite tests.test_variable_inventory tests.test_variable_ranges tests.test_variable_rewrite -v
  conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/inventory.py rtl_obfuscator/project.py rtl_obfuscator/rewrite.py rtl_obfuscator/category_profile.py tests/test_t035_profile_unification.py
  for f in tests/fixtures/t033_impact_category/*.sv; do conda run -n rtl_obfuscation verible-verilog-syntax "$f" || exit 1; done
  conda run -n rtl_obfuscation iverilog -g2012 -t null tests/formal/t032_project_root_parameters/child.sv tests/formal/t032_project_root_parameters/top.sv
  git diff --check
  conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-project --filelist tests/formal/t032_project_root_parameters/design.f --source-root tests/formal/t032_project_root_parameters --top t032_top --output-dir /private/tmp/rtl-obfuscation-t035-main-formal.iEd172/gate --map /private/tmp/rtl-obfuscation-t035-main-formal.iEd172/mapping.json --metrics /private/tmp/rtl-obfuscation-t035-main-formal.iEd172/metrics.json --name-length 8 --category modules --category ports --category parameters --category instances
  conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist tests/formal/t032_project_root_parameters/design.f --gold-root tests/formal/t032_project_root_parameters --gate-filelist /private/tmp/rtl-obfuscation-t035-main-formal.iEd172/gate/design.f --gate-root /private/tmp/rtl-obfuscation-t035-main-formal.iEd172/gate --top t032_top
  same formal command against a copied gate with only assign data_o = child_data; changed to assign data_o = ~child_data;
independent_results: |
  Non-RISC regression: 106 tests, 115.785s, OK. py_compile=0; Verible=0; Icarus=0 with only the known constant-select warning; git diff --check=0. No RISC-V-Vector test or Formal flow was run.
formal_recheck: PASS; positive JSON {"formal_equivalence":"pass","gate":"/private/tmp/rtl-obfuscation-t035-main-formal.iEd172/gate","gold":"tests/formal/t032_project_root_parameters","seq":5,"top":"t032_top"}; intentional negative exit=1 after equiv_status -assert with 8 unproven $equiv cells.
regression_result: PASS; shared 19-category registry, 13-category default profile, manual/alias profiles, bounded closure, mapping v4, transactional publish, v1/v2/v3 decrypt compatibility, determinism, per-file maps and metrics all passed.
git_status: Worktree contains only the documented T035 implementation, test, documentation and task-contract changes; no commit or push performed before this acceptance record.
staged_diff_review: Pending Git handoff after this status transition.
acceptance_conclusion: PASS; T035 is ACCEPTED by the Main Agent.
~~~
