# Self-built Frontend Deployment

This guide documents the **self-built frontend** (Vue 3 SPA + Fastify BFF) that can replace the
prebuilt GHCR frontend on a QuantDinger server. It assumes the host-level Nginx setup described in
[Cloud Deployment](CLOUD_DEPLOYMENT_EN.md): the host Nginx proxies the public domain (including
`/api` and `/ws`) to `127.0.0.1:8888`, and TLS is managed by Certbot.

Validated on `shark.aiorz.cc` (Alibaba Cloud ECS, `x86_64`) on 2026-10-10.

## Architecture

- Host Nginx terminates TLS and forwards **all** traffic (SPA, `/api`, and `/ws` with WebSocket
  upgrade headers) to `127.0.0.1:8888`.
- `sharkfe-web` — nginx serving the built SPA; `127.0.0.1:8888->80`.
- `sharkfe-bff` — Fastify BFF; proxies `/api` and `/ws` to the backend (`http://backend:5000`).
- Both containers join the existing Docker network `quantdinger_quantdinger-network` (external), so
  the BFF reaches the backend by service name. Host Nginx/TLS/DNS need no change.

## Prerequisites

Build the images **for the server architecture**. Images built on Apple Silicon are `arm64` and
will not run on an `x86_64` server — build natively on the server (recommended) or use
`docker buildx --platform linux/amd64`.

## Deploy

1. Copy the frontend source to the server (exclude `node_modules`, `dist`, `.git`):
   ```bash
   tar czf /tmp/fe.tgz -C frontend --exclude=node_modules --exclude=dist --exclude=.git .
   scp /tmp/fe.tgz root@SERVER:/tmp/fe.tgz
   ssh root@SERVER 'mkdir -p /root/QuantDinger/frontend-selfbuilt && tar xzf /tmp/fe.tgz -C /root/QuantDinger/frontend-selfbuilt'
   ```
2. Build the images on the server:
   ```bash
   cd /root/QuantDinger/frontend-selfbuilt
   docker build -t sharkfe-web:1 -f Dockerfile .
   docker build -t sharkfe-bff:1 -f bff.Dockerfile .
   ```
3. Create `docker-compose.yml` in that directory:
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
         - "127.0.0.1:8888:80"
       depends_on: [bff]
       restart: unless-stopped
       networks: [qdnet]
   networks:
     qdnet:
       external: true
       name: quantdinger_quantdinger-network
   ```
4. Cut over (brief downtime while port `8888` is released):
   ```bash
   docker stop quantdinger-frontend
   docker compose -f /root/QuantDinger/frontend-selfbuilt/docker-compose.yml up -d
   ```

## Verify

```bash
curl -fsS -o /dev/null -w '%{http_code}\n' https://YOUR_DOMAIN/            # 200
curl -fsS -o /dev/null -w '%{http_code}\n' https://YOUR_DOMAIN/api/health  # 200
curl -s https://YOUR_DOMAIN/ | grep -o '<title>[^<]*</title>'              # your SPA title
```

## Updating the frontend

Copy the new source (step 1), rebuild with a new tag (step 2), bump the image tags in the compose
file, then `docker compose -f /root/QuantDinger/frontend-selfbuilt/docker-compose.yml up -d`.

## Rollback

Restore the original GHCR frontend container:

```bash
docker compose -f /root/QuantDinger/frontend-selfbuilt/docker-compose.yml down
docker start quantdinger-frontend
```

The original image is `ghcr.io/openbyteinc/quantdinger-frontend:${FRONTEND_TAG}`. Before any
cutover, back up the project-root `.env`, `docker-compose.yml`, and `docker inspect` output of the
running frontend under `backups/`.

> Tip: to keep a later `docker compose up -d` in the project root from re-binding `8888` (the
> original `frontend` service is profile-less), set `FRONTEND_PORT` in the root `.env` to a free
> port such as `8890`.
