---
name: nav-manager
description: 将部署完成的应用或用户指定的网站登记到个人导航，按固定项目与环境标识更新名称和地址，或查询已有收藏。通过标准 HTTP API 和独立令牌操作，适用于支持运行 Python 或 HTTP 请求的开发 AI。
---

# 导航管理

使用本目录的 `scripts/nav.py`，仅依赖 Python 3 标准库。地址和凭据从环境变量 `NAV_URL`、`NAV_API_TOKEN` 读取。配置方法、示例见 [使用说明](references.md)。凭据不写入命令参数、聊天或源码。

## 登记流程

1. 从部署回执、运行配置或用户明确提供的信息取得实际访问地址。缺少地址时先查询；不可根据项目名猜域名，也不可用示例域名登记。
2. 确定长期稳定的 `项目-环境` key。生产和测试使用不同 key；同一环境的内外网双入口使用 `项目-环境-public` 与 `项目-环境-lan`。更名、迁移和更换域名沿用原 key。普通收藏也给定稳定 key，让网络重试保持幂等；不确定已有记录时先 search 和 get。
3. 明确分类；现有分类优先。归属按用户配置选择个人、工作或其他；无法确认的环境使用 none。
4. 执行 `upsert`。已有记录默认保留分类、排序、置顶和图标；用户明确要求移动分类才传 `--move-category`。更新时只传本次掌握的字段；清空说明传 `--description ''`。
5. 脚本会再次 get 核对保存结果。仅在退出码 0 且 confirmed 为 true 时报告登记完成，简短返回名称、分类、created/updated/unchanged。网络失败或回读不一致应说明状态，保留固定 key 供重试，不把登记失败误称为应用部署失败。

## 常用命令

```bash
python3 scripts/nav.py search '政策'
python3 scripts/nav.py get policy-assistant-prod
python3 scripts/nav.py upsert --key policy-assistant-prod --name '政策解读助手' \
  --url "$DEPLOYED_URL" --category '个人应用' --description '政策文件解析与问答' \
  --organization 个人 --network public --environment production
python3 scripts/nav.py upsert --key policy-assistant-prod --url "$NEW_DEPLOYED_URL"
python3 scripts/nav.py upsert --key policy-assistant-prod --category '工作网站' --move-category
```

脚本最多尝试 3 次，每次请求超时 15 秒；固定 key 的 upsert 可安全重试。HTTP 认证、参数或冲突错误直接失败。重定向不携带令牌跟随。
