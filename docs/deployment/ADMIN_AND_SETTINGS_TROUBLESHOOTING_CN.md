# 管理员凭据与系统设置保存排错指南

本文说明 Docker 部署中的初始管理员凭据、已有数据库数据卷，以及系统设置页面
因写入权限导致的保存失败问题。

其他安装问题请参阅[安装排错指南](INSTALL_TROUBLESHOOTING.md)。

## 初始管理员行为

数据库为空时，SharkQuant 会使用 `ADMIN_USER`、`ADMIN_PASSWORD` 和可选的
`ADMIN_EMAIL` 创建初始管理员。密码以哈希保存（标准镜像使用 bcrypt），不会
保存明文。

为保持向后兼容，手动 Docker 部署如果没有修改示例管理员配置，仍可使用
`quantdinger` / `123456` 登录。不要把该默认凭据暴露到公网；请在首次启动前
设置非默认密码，或首次登录后立即修改。一键安装器会拒绝用户选择 `123456`
作为密码。

已有 PostgreSQL 数据卷会被视为需要保留的用户数据。修改 `ADMIN_USER` 或
`ADMIN_PASSWORD` 不会无条件覆盖现有账户。只有同时满足以下条件时，系统才会
自动迁移旧默认管理员：

- 第一个活动管理员仍使用用户名 `quantdinger` 和密码 `123456`；
- 环境文件中明确配置了有效且非默认的管理员用户名和密码；
- 目标用户名没有被其他账户占用。

如果管理员已经修改过密码，SharkQuant 绝不会覆盖。如果目标用户名已经被
其他账户使用，系统会停止迁移，而不是自动提权或合并该账户。

## 系统设置提示保存失败

系统设置页面会直接写入 `/app/.env`。它在宿主机上对应：

| 部署方式 | 宿主机文件 |
| --- | --- |
| 所有受支持的 Compose 部署 | 项目根目录 `.env` |

后端应用以 UID/GID `10001` 运行。当前后端镜像先以 root 启动，初始化挂载文件，
把 `/app/.env` 的所有权调整为 `10001:10001`、权限收紧为 `600`，然后再降权。
一键安装和手动 Docker Compose 安装都会执行这套逻辑。

检查运行用户和写权限：

```bash
docker compose exec -u 10001:10001 -T backend sh -c '
  id
  ls -ln /app/.env
  test -r /app/.env && test -w /app/.env \
    && echo writable=yes || echo writable=no
'
```

如果手动下载后使用的是 `docker-compose.ghcr.yml`，请在 `docker compose` 后面
加上 `-f docker-compose.ghcr.yml`。

正常结果应包含 UID `10001`、文件所有者和组 `10001 10001`、权限 `600`，以及
`writable=yes`。

### 修复仍使用旧镜像的部署

应先更新后端镜像。只重新下载 `install.sh` 不会更新已经运行的容器：

```bash
docker compose pull backend
docker compose up -d --force-recreate backend
```

如果旧镜像留下了 root 所有的宿主机文件，只修复后端运行配置文件：

```bash
# 所有受支持的 Compose 部署
sudo chown 10001:10001 .env
sudo chmod 600 .env
```

不要使用 `chmod 755` 或 `chmod -R 777`。这些文件包含管理员凭据、API Key、
OAuth Secret 以及券商或交易所设置。`755` 会让其他本地用户读取敏感信息，
而且仍不能让 UID `10001` 写入 root 所有的文件。

### 宿主机普通用户被挡在 `.env` 外（Linux 上以普通用户运行 Compose）

同一套所有权修正会在 Linux 宿主机上**反向**生效：`.env` 通过 bind-mount 挂入
容器，backend（以及任何 worker、migration）每次启动时都会在容器内把**宿主机上的
这个文件**改成 `10001:10001`、权限 `600`。此后你的登录用户无法读取它——
`docker compose …` 会因读不到 `.env` 报权限错误（permission denied），直接编辑
也会被拒。已经在运行的容器不受影响：它们以 UID `10001` 运行，且运行中依赖该属主
读取热更新的配置（如 LLM 密钥）。

这是设计行为而非故障：应用必须以 UID `10001` 读写该文件，宿主机属主只能让位。
macOS / Windows 的 Docker Desktop 有虚拟化文件层、以 root 运行 Compose 的服务器
（如本项目生产环境）都不会遇到。

在保持 `10001` 属主的前提下：

- **编辑 `.env`**：用 sudo 编辑（如 `sudo vi .env`），完成后恢复属主与权限
  （也可以先不管——下次 backend 启动时入口脚本会自动校正）：

  ```bash
  sudo chown 10001:10001 .env && sudo chmod 600 .env
  ```

  ⚠️ 不要在栈运行时把文件 `chown` 给你的登录用户——应用（UID `10001`）会在
  同一刻失去读权限，设置保存与密钥热加载随之失败。
- **Compose 命令**：以 root 执行 `sudo docker compose …`；日常容器操作可以用
  不经 Compose 的 `docker start|stop|logs|exec`，这些命令不读 `.env`，无需 sudo。

## 券商连接失败（Alpaca / IBKR）

Alpaca 连接失败时，面板横幅会显示交易所返回的具体原因（如
「Alpaca rejected this Key/Secret (unauthorized) …」），不再是裸的 HTTP 状态码。
常见原因：

1. **Key 前缀与账户模式不匹配。** paper Key 以 `PK` 开头，必须选 **Paper**；
   实盘 Key 以 `AK` 开头，必须选 **Live**。不匹配会被判为 `unauthorized`。
2. **Secret 只显示一次。** Alpaca 创建 Key 对时只展示一次 Secret；若当时没保存，
   需要重新生成一对。
3. **Key 被轮换/吊销。** 到 Alpaca 后台重新生成。
4. **服务器出网。** 服务器必须能通过 HTTPS 访问 `paper-api.alpaca.markets` /
   `api.alpaca.markets`。可在宿主机上验证：

```bash
docker exec quantdinger-backend python -c "import socket; print(socket.create_connection(('paper-api.alpaca.markets',443),5).getpeername())"
```

面板上显示的基础 URL 是**主机名**（`https://paper-api.alpaca.markets`），不是
Alpaca 文档里的 `/v2` 端点路径：`alpaca-py` 会自行拼接 API 版本
（`url = base_url + "/" + version + path`），实际请求就是
`https://paper-api.alpaca.markets/v2/account`。若把 `.../v2` 传给 SDK 会拼成
`/v2/v2/...`；系统不允许自定义基础 URL，且会自动去掉多余的尾部 `/v2`。

已保存的凭据是 Fernet 密文存储；存储模型与 `.env` 主密钥运维见
[券商凭据存储](../security/CREDENTIAL_STORAGE_CN.md)。

## 只读挂载与特殊 Docker 部署

自动修复无法把有意设置的只读挂载变成可写。以下情况中，系统设置页面按设计
不可写：

- `/app/.env` 使用了 `:ro` 只读挂载；
- 启用了 `docker-compose.production.yml`；
- 容器通过 `user: 10001:10001` 强制从非 root 用户启动，无法预先调整所有权；
- rootless Docker、user namespace、NFS 或其他文件系统策略拒绝 `chown`。

加固只读部署请在宿主机修改环境文件，然后重建服务：

```bash
docker compose pull
docker compose up -d --force-recreate
```

返回[主 README](../../README.md)。
