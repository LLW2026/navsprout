# API v1

业务接口位于 `/api/v1`，要求 `Authorization: Bearer $NAV_API_TOKEN` 或网页会话。浏览器写请求另需登录返回的 `X-CSRF-Token`。API 令牌不通过 Cookie 传递，不受 CSRF 机制约束。整个导航为私有；无注册接口。

网页会话在服务端验证，默认 30 天有效；活跃会话至多每小时续期一次，普通读取无需续期写库。延长有效期后，仍有效的旧会话在下次访问时按新时长续期。到期、退出和账号凭据变更会使会话失效。

正常返回 `{"data": ...}`，登记额外返回 `result`；导出直接返回可导入的 JSON，网站图标接口返回图片或空响应。错误统一为：

```json
{"error":{"code":"unauthorized","message":"请先登录"}}
```

参数错误 422（附字段路径 `fields`）；未认证 401；跨站或 CSRF 失败 403；记录不存在 404；重复标识、重复分类或分类未清空 409；体积超限 413；登录频率限制 429；数据库暂忙 503（`Retry-After: 2`）。健康探测 `/healthz` 仅返回服务状态，不含导航内容。网页壳和本地静态资源可匿名加载，内容由认证 API 获取。登录后的完整 OpenAPI：`GET /api/v1/openapi.json`。

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| POST | `/auth/login` | `username`、`password` 登录；返回 CSRF |
| GET | `/auth/me` | 当前账号和 CSRF |
| POST | `/auth/logout` | 撤销当前服务端会话 |
| GET | `/links` | 列表；q、category、organization、network、environment 可筛选 |
| GET | `/links/{key}` | 按稳定标识读取 |
| GET | `/links/{key}/favicon` | 已保存网站的缓存图标；200 图片，204 暂无图标，404 链接不存在；同样要求认证 |
| POST | `/links` | 手动新增；key 可省略 |
| PATCH | `/links/{key}` | 修改给定字段，key 固定 |
| DELETE | `/links/{key}` | 删除链接 |
| POST | `/links/upsert` | 幂等登记 |
| POST | `/links/batch` | 批量修改、移动、置顶或删除，最多 500 条，单事务 |
| POST | `/links/move` | 拖动位置或分类；完整参数见下文 |
| POST | `/links/reorder` | `{"keys":["b","a"]}` 按顺序赋值 0、10…；事务执行 |
| GET | `/categories` | 分类及 link_count、lan_count、public_count，按排序值排列 |
| POST | `/categories/reorder` | `{"ids":[3,1,2]}` 必须包含全部分类，单事务保存 |
| POST | `/categories` | name，选填 sort_order |
| PATCH | `/categories/{id}` | name、sort_order |
| DELETE | `/categories/{id}` | JSON `{"move_to":目标分类ID}`；空分类可传 `{}` |
| GET | `/backgrounds` | 每日网络图片与历史/备用图片、抓取状态和下次更新时间 |
| GET | `/backgrounds/{日期-ID}.jpg` | 读取已保存的网络图片，仍需认证 |
| GET | `/export` | 全部分类、链接、标识、排序、置顶及时间 |
| POST | `/import` | 原子合并本站 version=1 JSON |

## 登记

```bash
curl --fail-with-body "$NAV_URL/api/v1/links/upsert" \
  -H "Authorization: Bearer $NAV_API_TOKEN" -H 'Content-Type: application/json' \
  --data '{"key":"policy-assistant-prod","name":"政策解读助手","url":"https://policy.example.com","category":"我的应用","description":"政策文件解析与问答"}'
```

上例网址仅为接口示例。自动部署请使用实际部署回执地址，优先调用不暴露令牌参数的 Skill 脚本。

- key 是 1–128 位字母、数字、点、下划线和短横线，首位为字母或数字。区分大小写。生产和测试分别设置 key，迁移和改名沿用 key。
- 新建要求 name、url，分类省略进入“未分类”；已有分类按规范化后的名称匹配，无则创建。事务与唯一约束阻止并发同名分类、重复 key。
- 更新仅改请求中提供的字段；未提供的字段保持原值。description、icon 清空用 `""`，pinned 用 false；null 不接受。name、url、category 不能清空。
- 更新默认保留 category；明确移动时加 `"move_category":true` 并提供 category。
- 更新默认保留 pinned、sort_order、icon，即使登记请求带了值。明确覆盖展示设置时加 `"update_presentation":true`。网页 PATCH 可直接修改这些字段。
- name、url、description、organization、network、environment 属于登记信息，提供时更新。
- 结果 created 返回 201；updated 或 unchanged 返回 200。unchanged 不改更新时间。响应含最终完整记录。
- SQLite 使用 WAL、BEGIN IMMEDIATE 写事务及 15 秒忙等待。脚本对网络和 502/503/504 最多重试 3 次；固定 key 防止重复。
- HTTP/HTTPS 域名、中文域名、IPv4、IPv6、单标签局域网名均可。拒绝内嵌账号密码、非法端口、空白和危险协议。保存时不请求目标网站。

## 字段与筛选

name 最大 120 字符，url 最大 2048，description 最大 500，icon 最大 16（手动指定的文字或 emoji）。icon 非空时优先使用；为空时网页尝试加载网站 favicon，失败则显示名称首字。category 最大 80。sort_order 为 -1000000 至 1000000 的整数，小值在前。

图标由服务端直接获取并缓存，不转发浏览器 Cookie 或 API 令牌。仅返回小型 ICO/PNG/GIF/JPEG/WebP 图片；失败缓存 1 小时，成功缓存 7 天。图标缺失或网站不可达不影响链接保存和读取。站点自身 `/favicon.ico` 是公开静态资源，不包含导航内容。

organization：个人、工作、其他。network：public、lan。environment：production、test、none（普通网站或暂未确定环境）。创建时间和更新时间由服务端生成 UTC ISO 格式；JSON 恢复时允许保留原时间。

q 为名称、说明、网址的关键词包含匹配，支持中文与大小写折叠。`%` 和 `_` 也是普通字符。前端置顶单独显示一次，分类按 sort_order、id，链接按 sort_order、key 排列。

## 导入合并

```json
{"version":1,"categories":[{"name":"我的应用","sort_order":0}],"links":[{"key":"policy-assistant-prod","name":"政策解读助手","url":"https://policy.example.com","category":"我的应用","description":"","icon":"","pinned":true,"sort_order":10,"organization":"个人","network":"public","environment":"production"}]}
```

分类按名称合并并更新文件内排序；链接按 key 合并，文件中提供的字段覆盖原值，包括分类、图标、置顶和排序。其余记录保留。同文件内重复 key、重复分类或任何非法条目使整个导入失败，不写入部分数据。上限 4 MB、500 分类、10000 链接。导入适合恢复已导出的快照；常规 AI 登记使用 upsert。

导出的 category_id 不参与迁移，使用分类名称关联；created_at 在新建时可保留，已存在记录仍保留其原创建时间。已有内容发生变化时更新时间取本次写入时间。

## 拖动与一键排序

网页和脚本复用以下接口，均需认证，浏览器写操作需 CSRF。仅更新发生变化的排序值和时间，不覆盖图标、名称等字段。

`POST /api/v1/links/move`

```json
{"key":"policy-assistant-prod","before_key":"another-app","category_id":3,"pinned":false}
```

- `key` 必填；`before_key` 为目标之前的记录，省略或 `null` 表示追加到末尾。拖到自身返回原记录。
- `category_id` 省略或 `null` 保留原分类；提供时移动到该分类。`pinned` 省略或 `null` 保留原状态，`true/false` 明确设置置顶。
- 非置顶在目标分类的完整非置顶集合中重排；置顶在全部分类的置顶集合中重排。隐藏于搜索、网络筛选的记录也会保留相对顺序。
- 分类移动、置顶状态和目标集合排序在一个写事务内完成。目标不存在 404；目标记录与分类/置顶范围不符 409 `order_changed`，全部回滚。返回保存后的 `data` 链接记录。

`POST /api/v1/links/reorder`

```json
{"keys":["app-b","app-a"],"complete":true,"category_id":3}
```

按给定顺序写为 0、10……，`complete` 默认 `false`（兼容原接口）。为 `true` 时要求 keys 恰好包含目标范围内的全部记录：指定 `category_id` 为该分类全部链接（含置顶）；省略或 `null` 为全站。并发新增/删除/移动造成集合变化时返回 409 `order_changed`，提示刷新后重试。重复标识 422，任何非法标识或范围均不写入部分结果。未指定完整集合时仍应提交完整视觉范围，避免子集排序造成与隐藏记录的排序值重叠。

网页一键排序先获取完整范围，使用浏览器 `Intl.Collator('zh-Hans-CN', {numeric:true})` 排序；置顶单独排序，普通链接在各分类内排序，再调用完整集合接口。分类顺序不受一键链接排序影响。

`POST /api/v1/categories/reorder` 传 `{"ids":[...]}`，必须包含当时全部分类；重复 ID 422，缺少、新增或不存在的 ID 409。单事务保存，避免原逐条 PATCH 在中途失败时只更新部分分类。

## 批量编辑

`POST /api/v1/links/batch`：

```json
{"operation":"move","category_id":3,"items":[{"key":"app-a","name":"修改后名称"},{"key":"app-b","description":""}]}
```

`items` 为 1 至 500 条，每条 key 必填，其余字段遵循手工 PATCH 的校验与清空规则。`operation` 默认为 `update`，还支持 `move`、`pin`、`unpin`、`delete`。移动时需要有效 `category_id`；置顶操作显式覆盖 pinned；除删除外可同时保存所选记录的字段修改。删除仅需 keys，建议不携带字段。

所有记录和目标分类先校验，再在同一个事务中更新；重复 key 返回 422，不存在的记录/目标分类返回 404，任意校验或写入错误整体回滚。未包含的记录保持不变。成功返回 `{"data":{"affected":2,"links":[...]}}`，删除时 links 为空。

## 每日网络背景

`GET /api/v1/backgrounds` 返回 `data.photos`（今日、最近 30 张记录及 8 张备用图片）、`daily_id`、`status`（ready/stale/fallback）、`refresh_time`、`timezone`、`next_refresh_at`、`enabled`。网络照片有 `downloaded_at`、`source_id`、`sha256`、实际 `width` / `height`、摄影者、来源与许可；其 image 为同域认证图片路径。备用图片为公开静态资源。

定时抓取在服务器运行，不由 GET 请求触发，不接受任意远程网址。无缓存或错过更新时间时启动后补取；失败保留旧图，每 10 分钟重试。只请求允许的 HTTPS 图源主机，不转发导航 Cookie 或令牌。背景缓存位于 `data/background-cache/`，不改变导航数据库结构，删除缓存后可自动重建。

## 同分类单层聚合

聚合是独立的展示记录，不替换链接或其 `key`。只允许同一分类的真实链接成为成员；一个链接最多属于一个聚合，不支持嵌套。创建至少两个成员，移出后允许保留一个成员；最后一个成员删除或移出时自动拆分。拆分始终保留网址。

| 方法 | 路径 | 行为 |
| --- | --- | --- |
| GET | `/groups` | 全部聚合及有序的成员 `keys` |
| POST | `/groups` | 创建，必填 `name`、`keys`，可选 `icon`、`pinned` |
| PATCH | `/groups/{key}` | 修改 `name`、`icon`、`pinned`、`sort_order`、`keys`、`category_id` |
| DELETE | `/groups/{key}` | 拆分，保留所有成员链接 |
| DELETE | `/groups/{key}/members/{link_key}` | 移出一个成员，保留链接 |
| POST | `/cards/reorder` | 普通卡片和聚合卡片混合排序 |
| POST | `/cards/move` | 普通卡片和聚合卡片拖动、移动、置顶 |

```json
{"name":"政策助手","keys":["policy-prod-public","policy-prod-lan"],"icon":"策"}
```

创建返回 201，其他成功返回 200 和 `data`。成员跨分类或已在其他聚合中返回 409；成员不存在或尝试嵌套返回 404；重复成员和缺少必要字段返回 422。所有写操作使用事务，失败整体回滚。

更新 `keys` 是完整替换成员列表，顺序即展开后的地址顺序。更新聚合 `category_id` 将全部现有成员一起移动；新增成员须已属于目标分类。单个链接通过原链接接口移动分类时会自动移出聚合。普通 upsert 更新名称、地址等信息保留成员关系。

混合卡片接口参数沿用 `/links/reorder` 和 `/links/move`，普通链接使用原 `key`，聚合卡片使用 `group:` 加聚合 `key`。只接收顶层卡片标识；已聚合成员不能作为顶层卡片排序。完整排序校验包含隐藏及置顶卡片，集合变化返回 409。网页使用混合接口；原链接接口继续适用于独立链接记录。

聚合自己的置顶、图标、排序与成员字段独立。网页展示以聚合设置为准，拆分后恢复成员原有设置。搜索同时匹配聚合名称与成员名称、说明、网址；网络和环境筛选仍按成员属性生效。

有聚合时导出 `version: 2`，新增 `groups` 数组（包括 `key`、`name`、分类名称 `category`、有序 `keys`、图标、置顶、排序和时间）。无聚合仍导出版本 1。导入同时支持两个版本；版本 2 必须包含 `groups`，聚合按 key 合并，成员必须存在且分类一致；同文件成员重复归属使整个导入回滚。版本 1 不清除已有聚合，但链接移动分类仍会自动移出。数据库结构升级为 v2；备份工具兼容 v1/v2，旧镜像回退须恢复升级前备份。
