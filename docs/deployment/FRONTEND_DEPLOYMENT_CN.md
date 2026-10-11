# 自建前端部署

本文档说明如何用**自建前端**（Vue 3 SPA + Fastify BFF）替换 QuantDinger 服务器上的原版 GHCR 前端。
它假定采用 [云部署](CLOUD_DEPLOYMENT_CN.md) 中的宿主机 Nginx 方案：宿主机 Nginx 把公网域名的全部流量
（含 `/api` 与 `/ws`）反代到 `127.0.0.1:8888`，TLS 由 Certbot 管理。

已于 2026-10-10 在 `shark.aiorz.cc`（阿里云 ECS，`x86_64`）验证。

## 架构

- 宿主机 Nginx 终止 TLS，并把**全部**流量（SPA、`/api`、带 WebSocket Upgrade 头的 `/ws`）转发到
  `127.0.0.1:8888`。
- `sharkfe-web` —— nginx 托管构建后的 SPA；`127.0.0.1:8888->8080`（镜像使用
  unprivileged nginx，容器内以非 root 监听 `8080`）。
- `sharkfe-bff` —— Fastify BFF；把 `/api` 与 `/ws` 反代到后端（`http://backend:5000`）。
- 两个容器都加入已存在的 Docker 网络 `quantdinger_quantdinger-network`（external），因此 BFF 可按服务名
  访问后端。宿主机 Nginx/TLS/DNS 均无需改动。

## 前置条件

镜像必须**按服务器架构构建**。在 Apple Silicon 上构建的是 `arm64` 镜像，无法在 `x86_64` 服务器运行 ——
请在服务器上原生构建（推荐），或用 `docker buildx --platform linux/amd64`。

## 部署

1. 把前端源码拷贝到服务器（排除 `node_modules`、`dist`、`.git`）：
   ```bash
   tar czf /tmp/fe.tgz -C frontend --exclude=node_modules --exclude=dist --exclude=.git .
   scp /tmp/fe.tgz root@SERVER:/tmp/fe.tgz
   ssh root@SERVER 'mkdir -p /root/QuantDinger/frontend-selfbuilt && tar xzf /tmp/fe.tgz -C /root/QuantDinger/frontend-selfbuilt'
   ```
2. 在服务器上构建镜像：
   ```bash
   cd /root/QuantDinger/frontend-selfbuilt
   docker build -t sharkfe-web:1 -f Dockerfile .
   docker build -t sharkfe-bff:1 -f bff.Dockerfile .
   ```
3. 在该目录创建 `docker-compose.yml`：
   ```yaml
   services:
     bff:
       image: sharkfe-bff:1
       container_name: sharkfe-bff
       environment:
         BACKEND_URL: http://backend:5000
         BFF_PORT: "8787"
       restart: unless-stopped
       networks: [qdnet]
     web:
       image: sharkfe-web:1
       container_name: sharkfe-web
       ports:
         - "127.0.0.1:8888:8080"
       depends_on: [bff]
       restart: unless-stopped
       networks: [qdnet]
   networks:
     qdnet:
       external: true
       name: quantdinger_quantdinger-network
   ```
4. 切流（释放 `8888` 端口时会有短暂中断）：
   ```bash
   docker stop quantdinger-frontend
   docker compose -f /root/QuantDinger/frontend-selfbuilt/docker-compose.yml up -d
   ```

## 验证

```bash
curl -fsS -o /dev/null -w '%{http_code}\n' https://YOUR_DOMAIN/            # 200
curl -fsS -o /dev/null -w '%{http_code}\n' https://YOUR_DOMAIN/api/health  # 200
curl -s https://YOUR_DOMAIN/ | grep -o '<title>[^<]*</title>'              # 你的 SPA 标题
```

## 更新前端

重新拷贝源码（第 1 步）→ 用新 tag 重建镜像（第 2 步）→ 更新 compose 里的镜像 tag →
`docker compose -f /root/QuantDinger/frontend-selfbuilt/docker-compose.yml up -d`。

## 回滚

恢复原版 GHCR 前端容器：

```bash
docker compose -f /root/QuantDinger/frontend-selfbuilt/docker-compose.yml down
docker start quantdinger-frontend
```

原版镜像为 `ghcr.io/openbyteinc/quantdinger-frontend:${FRONTEND_TAG}`。切流前请把项目根 `.env`、
`docker-compose.yml`、以及运行中前端容器的 `docker inspect` 输出备份到 `backups/`。

> 提示：为避免日后在项目根执行 `docker compose up -d` 时原 `frontend` 服务（无 profile）重新占用 `8888`，
> 可把根 `.env` 的 `FRONTEND_PORT` 改为空闲端口（如 `8890`）。
