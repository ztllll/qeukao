# 数据模型

## 1. 上报记录表

建议表名：`absence_reports`

| 字段 | 类型建议 | 是否必填 | 说明 |
| --- | --- | --- | --- |
| `id` | integer / uuid | 是 | 主键 |
| `title` | string | 是 | 上报标题 |
| `exam_date` | date | 是 | 考试日期 |
| `exam_time` | string | 否 | 考试时间段 |
| `room_name` | string | 是 | 教室或考场 |
| `subject_name` | string | 否 | 科目名称 |
| `class_name` | string | 否 | 班级或批次 |
| `reporter_name` | string | 是 | 填报人 |
| `reporter_contact` | string | 否 | 填报人联系方式 |
| `expected_count` | integer | 是 | 应到人数 |
| `actual_count` | integer | 是 | 实到人数 |
| `absent_count` | integer | 是 | 缺考人数，服务端计算 |
| `attendance_rate` | decimal | 是 | 出考率，服务端计算 |
| `absent_students_text` | text | 否 | 缺考学生名单文本 |
| `remark` | text | 否 | 备注 |
| `client_ip` | string | 否 | 提交设备 IP |
| `created_at` | datetime | 是 | 创建时间 |
| `updated_at` | datetime | 是 | 更新时间 |

## 2. 计算规则

### 缺考人数

```text
缺考人数 = 应到人数 - 实到人数
```

校验规则：

- 应到人数必须大于或等于 0。
- 实到人数必须大于或等于 0。
- 实到人数不能大于应到人数。
- 如果应到人数为 0，出考率按 0 处理，或根据业务规则显示为 `-`。

### 出考率

```text
出考率 = 实到人数 / 应到人数 * 100%
```

建议数据库中保存小数，例如：

- `1.0000` 表示 100%。
- `0.8750` 表示 87.5%。

前端展示时格式化为百分比。

## 3. 后台汇总模型

后台按当前筛选条件汇总：

| 字段 | 说明 |
| --- | --- |
| `report_count` | 上报记录总数 |
| `total_expected_count` | 应到总人数 |
| `total_actual_count` | 实到总人数 |
| `total_absent_count` | 缺考总人数 |
| `overall_attendance_rate` | 总体出考率 |

总体出考率计算：

```text
总体出考率 = 实到总人数 / 应到总人数 * 100%
```

## 4. 后续扩展：结构化缺考学生

如果需要统计到学生级别，可增加 `absent_students` 表。

| 字段 | 类型建议 | 是否必填 | 说明 |
| --- | --- | --- | --- |
| `id` | integer / uuid | 是 | 主键 |
| `report_id` | integer / uuid | 是 | 关联上报记录 |
| `student_name` | string | 是 | 学生姓名 |
| `student_no` | string | 否 | 学号 |
| `class_name` | string | 否 | 班级 |
| `reason` | string | 否 | 缺考原因 |
| `remark` | text | 否 | 备注 |

第一版可以先不建该表，使用文本字段降低实现复杂度。
