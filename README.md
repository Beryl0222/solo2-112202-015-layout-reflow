# 设备培训讲义中的图注接续与工步同步

业务资料使用虚构编号和合成叙述。文本保持来件拼写和措辞。各表是独立的来源记录。
TSV 文件采用 UTF-8，首行为列名。行首 id 是该表的稳定记录号，空格和标点属于原文，空单元格表示来件未填。
日期时间采用所在地本地时间。资料内注明为编号列表的字段用竖线分隔。

## 资料字段

- `materials/blocks.tsv`。box 采用页内 x,y,宽,高，单位为资料像素，仅供理解原始版面。kind 是装订时的实体类型。
- `materials/classrooms.tsv`。access 记录学生实际可看到哪些材料，model 是对应教具修订。phase 为发放状态。
- `materials/attempts.tsv`。block 对应老师登记的学生所看资料。archive 表示实际已消费材料的实操。
- `materials/aids.tsv`。illustration 关联原文的图号，orientation 是讲师已登记的实物训练朝向。

## 运行资料检查

使用 CPython 3.11.2 和标准库。资料检查仅读取输入。

```sh
python3 pack_check.py
python3 -m unittest -v
```
