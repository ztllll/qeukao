# 接口草案

本文件先定义业务接口方向，具体路径、字段名和返回结构可在确定技术栈后继续调整。

## 1. 普通用户接口

### 当前场次缺考上报

```http
POST /api/current-reports
```

请求示例：

```json
{
  "title": "2026年春季期末考试数学缺考上报",
  "examDate": "2026-06-20",
  "roomName": "一教室",
  "expectedCount": 45,
  "actualCount": 43
}
```

服务端处理：

- 校验当前教室是否已有未验收数据。
- 校验人数逻辑。
- 计算 `absentCount = expectedCount - actualCount`。
- 计算 `attendanceRate = actualCount / expectedCount`。
- 保存到数据库和当前未验收列表。

响应示例：

```json
{
  "success": true,
  "data": {
    "items": [
      {
        "reportId": 1,
        "roomName": "一教室",
        "expectedCount": 45,
        "actualCount": 43,
        "absentCount": 2,
        "attendanceRate": 0.9556
      }
    ]
  }
}
```

### 校验教室是否可填报

```http
POST /api/current-reports/check-room
```

如果该教室已有未验收数据，返回冲突错误，提示联系考务老师确认。

## 2. 管理员认证接口

### 管理员登录

```http
POST /api/admin/login
```

请求示例：

```json
{
  "password": "admin-password"
}
```

响应示例：

```json
{
  "success": true
}
```

建议登录成功后由服务端设置 HttpOnly Cookie，后台接口通过 Cookie 校验登录状态。

### 退出登录

```http
POST /api/admin/logout
```

## 3. 管理员数据接口

### 查询上报列表

```http
GET /api/admin/reports?date=2026-06-20&keyword=数学&page=1&pageSize=20
```

查询参数：

| 参数 | 是否必填 | 说明 |
| --- | --- | --- |
| `date` | 否 | 按考试日期筛选 |
| `keyword` | 否 | 按标题或相关字段模糊搜索 |
| `page` | 否 | 页码 |
| `pageSize` | 否 | 每页数量 |

响应示例：

```json
{
  "success": true,
  "data": {
    "items": [
      {
        "id": 1,
        "title": "2026年春季期末考试数学缺考上报",
        "examDate": "2026-06-20",
        "roomName": "教学楼 A101",
        "subjectName": "数学",
        "expectedCount": 45,
        "actualCount": 43,
        "absentCount": 2,
        "attendanceRate": 0.9556,
        "reporterName": "张老师",
        "createdAt": "2026-06-20T09:30:00+08:00"
      }
    ],
    "total": 1,
    "page": 1,
    "pageSize": 20
  }
}
```

### 查询汇总数据

```http
GET /api/admin/reports/summary?date=2026-06-20&keyword=数学
```

响应示例：

```json
{
  "success": true,
  "data": {
    "reportCount": 1,
    "totalExpectedCount": 45,
    "totalActualCount": 43,
    "totalAbsentCount": 2,
    "overallAttendanceRate": 0.9556
  }
}
```

### 查询上报详情

```http
GET /api/admin/reports/1
```

响应返回单条记录完整字段。

## 4. 错误响应建议

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "实到人数不能大于应到人数"
  }
}
```

常见错误码：

- `VALIDATION_ERROR`：表单字段校验失败。
- `UNAUTHORIZED`：管理员未登录或登录失效。
- `FORBIDDEN`：权限不足。
- `NOT_FOUND`：数据不存在。
- `INTERNAL_ERROR`：服务器内部错误。
