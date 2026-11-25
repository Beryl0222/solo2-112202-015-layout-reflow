# 设备培训讲义中的图注接续与工步同步

业务资料使用虚构编号和合成叙述。文本保持来件拼写和措辞。各表是独立的来源记录。
TSV 文件采用 UTF-8，首行为列名。行首 id 是该表的稳定记录号，空格和标点属于原文，空单元格表示来件未填。
日期时间采用所在地本地时间。资料内注明为编号列表的字段用竖线分隔。

## 资料字段

- `materials/blocks.tsv`。box 采用页内 x,y,宽,高，单位为资料像素，仅供理解原始版面。kind 是装订时的实体类型。
- `materials/classrooms.tsv`。access 记录学生实际可看到哪些材料，model 是对应教具修订。phase 为发放状态。
- `materials/attempts.tsv`。block 对应老师登记的学生所看资料。archive 表示实际已消费材料的实操。
- `materials/aids.tsv`。illustration 关联原文的图号，orientation 是讲师已登记的实物训练朝向。
- `materials/issue_log.tsv`。打印与发放签收，recipient 是收到材料的操作角色。
- `materials/sheet_notes.tsv`。印务和教师对来源版面的观察。

## 项目结构

`training_pack/` 只使用 CPython 3.11.2 标准库，按“工人实际拿到的一页或一叠”
把可练工步与需要老师解释/暂停的工步分开：

| 模块 | 职责 |
| --- | --- |
| `geometry.py` | 页内 box 与双栏/跨栏判断；“右图”只解析为版面右栏，不是工人站位的右 |
| `figures.py` | 图号登记：图、图注、勘误、角注只按显式“图 N/Fig. N”关联，不按距离归属；登记视角冲突与遮挡对象 |
| `discourse.py` | 句段恢复、小句切分、连接词作用（时序/指代/版面指示/条件/搭档协同/跨页） |
| `steps.py` | 工步抽取、跨页指代回溯、模块范围（显式 M 标记与跨语言动作对齐，不做几何归属）、静态语义风险 |
| `distribution.py` | 按 issue_log 实际发放与页面可见范围逐角色评估；模型门槛、先行对象缺失、旧视角、方向独占 |
| `planning.py` | 三种合法组织方式（by_step/by_figure/as_issued）、暂停与替代练习、平板同屏 bundle、台位结论 |
| `audit.py` | 课后追溯：学生实际看到哪份图、有效视角、仍可核对什么、按角色的授权操作 |
| `revision.py` | 教师更正（图号/朝向/遮挡/译文）与改图后的换页或收卡决策；支持下一批讲义重走发放 |
| `report.py` | 教师可读文本与可下发系统的 JSON 渲染 |

## 关键业务口径

1. **图号不按距离归属**：混排英文图注、两个模块共用一张图（图 3 支持 M1/M2）时，
   只认显式图号与显式 M 标记；中文工步的模块范围只通过跨语言同动作对齐回填。
2. **遮挡只阻断受影响工步**：图 2 右槽标签未随勘误重印、图 3 白卡仅虚线轮廓，
   只让依赖这些标注的工步语义不确定，同图其他段保留可用。
3. **译文调换是语言风险不是整步作废**：中文“先拔卡、搭档再核对”与英文
   `when the partner confirms` 的条件顺序调换，标记 `TRANSLATION_SWAP`，
   工步保留，老师做语言校订即可。
4. **一切以实际发放为准**：更正只对拿到更正页/重印卡的角色生效；发给操作者的
   勘误不会提升搭档手里旧图的版本。旧版引用仍按签收与页面可见范围核对。
5. **限新模型工步不进旧版包**：M2 拔白卡工步（B7-3/B7-4 及对齐到的 B5-2）
   在 M1 教室判为 `gated`，不进入练习包。
6. **双人方向不被对方独占**：搭档核对方向必须有本方视角材料；只听操作者转述
   判为 `PARTNER_MONOPOLY_RISK`。信息看不全的工步暂停，并给出不依赖它的替代练习。
7. **改图决策**：视角翻转的实物卡（图 2）基线即收回；局部遮挡（图 3）默认只换
   讲义页，教师发起实物重印更正时才收卡并暂停继续发放。

## 运行

资料检查仅读取输入。读取外部资料目录的命令建议使用 `-I`，路径全部以参数传入：

```sh
python3 pack_check.py
python3 -I cli.py plan --classroom C2
python3 -I cli.py plan --classroom C2 --grouping by_figure
python3 -I cli.py plan --classroom C2 --corrections examples/teacher_corrections.json
python3 -I cli.py station --classroom C3
python3 -I cli.py audit
python3 -I cli.py revision --classroom C2 --figure '图 2'
python3 -I cli.py --json out.json plan --classroom C2
python3 -m unittest -v
```

教师更正文件格式见 `examples/teacher_corrections.json`；下一批讲义重走发放
（含正视重印卡解除遮挡）由 `tests/test_revision.py` 的合成资料目录演示。

## 工步状态

| 状态 | 含义 |
| --- | --- |
| `practicable` | 材料齐、语义确定，可直接练 |
| `teacher_required` | 仅待语言/视角约定校订，老师解释后可练 |
| `held` | 必要信息看不全（旧视角、遮挡、先行对象缺失、方向独占、未发放），暂停 |
| `gated` | 限新模型工步，不得进入本台（旧模型）练习包 |
