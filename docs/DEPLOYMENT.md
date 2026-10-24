# 部署与维护

## 初始化与持久化

按 README 安装依赖后运行 `scripts/setup.py`。默认账号 `admin`，密码随机生成并写入 `~/.config/navsprout/admin-password.txt`；登记配置在同目录的 `nav-manager.env`。两个文件及项目 `.env` 均为 0600。如已有这些文件，初始化不会覆盖。

默认端口 8866，使用 `--port`、`--lan-ip`、`--domain` 指定实际配置。修改已有配置时直接编辑 `.env`，再 `docker compose up -d --force-recreate`。配置中的 IP、域名均由部署者提供；`NAV_DB=/data/nav.db` 是容器内部路径。

`data/` 独立挂载，`NAV_UID` / `NAV_GID` 应与有权访问该目录的本机用户一致。使用 SQLite WAL 和事务迁移，升级不重建已有业务数据。缓存图片位于 `data/background-cache/`，图标位于 `data/favicon-cache/`。

## HTTPS 与局域网

可同时保留 `http://服务器IP:8866` 和 `https://自己的域名`。这两个入口共用服务器数据，浏览器登录和外观偏好按来源分别保存。

将 `NAV_ALLOWED_HOSTS` 设置为实际 Host 列表，`NAV_ALLOWED_ORIGINS` 为完整协议、主机和端口列表。`NAV_HTTPS_HOSTS` 只包含走 HTTPS 的域名，用于在反向代理后设置 Secure Cookie。

- Caddy：修改 `deploy/nav.Caddyfile` 的域名和回源地址，校验并重载现有 Caddy。
- Nginx：修改 `deploy/nginx.conf.example` 的域名、证书及回源地址，校验并重载现有 Nginx。
- 代理同机时回源 `127.0.0.1:8866`；代理位于另一主机时使用实际可达的内网或受保护隧道地址。
- 保留 Host 和 Authorization；代理日志不记录请求体、Cookie 或 Authorization。

模板不会自动安装证书、修改 DNS 或配置跨主机隧道，这些由现有反向代理和网络环境提供。

## 登录与密钥

本项目不开注册。密码使用 Argon2id，Cookie 内为签名后的不透明会话 ID；会话、CSRF 和有效期保存在 SQLite。默认空闲 30 天到期，活跃会话定期续期，退出时立即撤销。HTTPS Cookie 启用 Secure、HttpOnly、SameSite=Lax。

更改用户名、密码哈希或会话密钥会使原会话失效。更新 API 令牌后同步调用端受保护配置。生成新密码哈希：

```bash
.venv/bin/python -c 'from getpass import getpass; from argon2 import PasswordHasher; print(PasswordHasher().hash(getpass("新密码: ")))'
```

将结果用单引号写入 `.env` 的 `NAV_PASSWORD_HASH`，再重建容器。真实密码和令牌不放在命令参数中。

## 检查

```bash
docker compose ps
curl --fail http://127.0.0.1:8866/healthz
# 未登录应返回 401
curl -i http://127.0.0.1:8866/api/v1/links
docker compose logs --tail 50 nav
```

健康检查之外，还应实际登录并检查私有 API 和一次写入回读。公网异常时分别检查后端、回源网络和反向代理。

## 备份与升级

```bash
python3 scripts/database.py backup data/nav.db backups/nav-before-upgrade.db
docker compose up -d --build
# 恢复时先停止应用
# docker compose stop nav
# python3 scripts/database.py restore backups/nav-before-upgrade.db data/nav.db --app-stopped
# docker compose up -d
```

备份使用 SQLite backup API，包含 WAL 已提交内容，恢复前验证完整性并清除旧会话。不要在运行时只复制主数据库文件。另行保护 `.env` 和备份，建议复制到独立存储。数据库结构回退需与备份版本匹配。

## 每日背景

默认每天北京时间 06:00 后台取新图，`NAV_BACKGROUND_REFRESH_TIME` 可调整；`NAV_BACKGROUND_ENABLED=false` 可关闭网络任务。失败保留旧图并重试，首次没有缓存时使用内置备用图。详见 [图源与缓存](BACKGROUNDS.md)。
