# 配置与接入

在受保护环境中设置，以下仅为占位值：

```bash
export NAV_URL='https://nav.example.com'
export NAV_API_TOKEN='replace-with-dedicated-token'
```

初始化生成的本机配置在 `~/.config/navsprout/nav-manager.env`（0600），可使用：

```bash
set -a
. "$HOME/.config/navsprout/nav-manager.env"
set +a
python3 /absolute/path/skills/nav-manager/scripts/nav.py search '应用'
```

其他主机将该 Skill 文件夹复制到支持的技能目录，并通过自己的受保护配置注入变量。使用 HTTPS 公网地址，或同一局域网的 NAS HTTP 地址。不依赖 SSH 或某一种 AI 产品。

## 部署收尾

在应用部署与健康检查成功、取得真实地址以后执行：

```bash
# DEPLOYED_URL 由部署工具实际输出，PROJECT_KEY 在项目配置中长期保存。
: "${DEPLOYED_URL:?缺少确认后的部署地址}"
: "${PROJECT_KEY:?缺少稳定的项目与环境标识}"
python3 /path/to/nav-manager/scripts/nav.py upsert \
  --key "$PROJECT_KEY" --name "$APP_NAME" --url "$DEPLOYED_URL" \
  --category '我的应用' --environment production --network public
```

普通网站收藏示例（实际使用时填写真实网址）：

```bash
python3 scripts/nav.py upsert --key work-standards --name '工作资料' \
  --url "$CONFIRMED_WEBSITE_URL" --category '工作网站'
```

查询成功返回 `data`；登记成功返回 `result`、`confirmed`、保存后的 `data`，退出码 0。缺少配置、网络错误、参数错误或回读冲突退出码 1，参数用法错误为 2。脚本正常输出不含令牌。
