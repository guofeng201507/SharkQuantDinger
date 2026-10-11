# Security audit — 2026-10-11

Scope: the shipped solution — `backend_api_python`, `mcp_server`, the self-built
frontend (`frontend/web` + `frontend/bff`), and the Docker/nginx deployment on
the Alibaba Cloud host. Method: the `security-analyzer` skill (environment
discovery + OSV.dev CVE lookup) plus an OWASP A06 misconfiguration pass
(`security-misconfiguration`).

## Results

| Area | Check | Result |
|---|---|---|
| Dependencies | 62 shipped deps (41 pip / 21 npm) against OSV.dev | **0 known vulnerabilities** |
| Dependencies | `npm audit --omit=dev` (web + bff) | **0 vulnerabilities** |
| Secrets | `.env` ignored in all three trees; image contains no `/app/.env` (verified by inspecting the built image); tracked files clean (one benign test fixture) | **pass** |
| Secrets | `.env.bak*` permissions | **fixed** — 0644 → 0600 |
| Network | Service ports (`5432/6379/29092/5000/8888/8890`) all bound to `127.0.0.1`; host listens publicly only on 22/80/443; `/api/openapi.json` not served (404) | **pass** |
| HTTP headers | `shark.aiorz.cc` previously served **no** security headers | **fixed** — see below |
| HTTP headers | `legacy.aiorz.cc` missing HSTS | **fixed** (host vhost) |
| Version disclosure | `Server: nginx/1.24.0 (Ubuntu)` | **fixed** — `server_tokens off` on both vhosts |
| CORS | Explicit origin allowlist, `send_wildcard=False`, `supports_credentials=False` | **pass** |
| Credential storage | Fernet ciphertext, per-user scoping, hint-only API | **pass** — see [CREDENTIAL_STORAGE](CREDENTIAL_STORAGE.md) |

## Fixed in this pass

- `frontend/nginx.conf` + `security-headers.conf`: X-Content-Type-Options,
  X-Frame-Options, Referrer-Policy, Permissions-Policy, HSTS, enforced
  `frame-ancestors 'self'` CSP, and the full CSP in **report-only** mode.
  nginx drops inherited `add_header` directives in any location that declares
  its own, so the snippet is included explicitly in the server scope and in the
  two locations that set `Cache-Control` (the SPA shell itself).
- Host nginx: HSTS on the legacy vhost, `server_tokens off` on both vhosts
  (backups in `/root/nginx-backups/`).
- Verified after deploy: `/` and `/portfolio` render with **0 console errors**
  and no CSP report-only violations on the proposed policy.

## Open items (recommended, not auto-applied)

1. **Containers run as root** (`quantdinger-backend`, `sharkfe-web`,
   `sharkfe-bff`). Converting to a non-root user needs volume-permission work
   (`logs/`, `data/`, `.env` writer UID) and should be done as its own change
   with a rollback plan.
2. **Host firewall inactive** (`ufw`). Exposure is currently limited by the
   127.0.0.1 bindings; confirm the Alibaba ECS security group allows only
   22/80/443 from the internet, and consider enabling `ufw` with those ports.
3. **Error verbosity**: several routes return raw exception strings to
   authenticated callers. Low risk for a single-tenant deployment; worth a
   sweep when touching those files.
4. **Promote the CSP** from report-only to enforced after a soak period with no
   violations.
5. **Key rotation**: replace `CREDENTIAL_ENCRYPTION_KEY` on a schedule and
   re-encrypt stored credentials afterwards (runbook in CREDENTIAL_STORAGE).

---

## 中文摘要

审计范围：实际部署的代码（后端 / MCP / 自建前端与 BFF / Docker 与 nginx）。
方法：`security-analyzer`（环境发现 + OSV.dev 漏洞库）＋ `security-misconfiguration`
（OWASP A06 配置错误）。

**结论**：依赖 0 已知漏洞（OSV 62 项 + npm audit 0）；密钥无泄漏（`.env` 三处均被忽略、
镜像内无 `.env`、跟踪文件干净）；网络暴露面干净（业务端口全部 127.0.0.1，公网仅 22/80/443，
openapi 未对外）；CORS 为显式白名单；凭据 Fernet 加密存储。

**本次已修复**：shark 站补齐 7 个安全响应头（含 HSTS、强制 frame-ancestors CSP、报告模式
完整 CSP）；legacy 站补 HSTS；两站关闭 `server_tokens`（隐藏版本号）；`.env.bak*` 权限收紧
到 0600。验证：部署后页面 0 控制台错误，报告模式 CSP 无违规。

**待办（建议，未自动执行）**：① 容器以 root 运行——改非 root 需处理卷权限，建议独立变更；
② 宿主机 `ufw` 未启用——请核对阿里云安全组仅放行 22/80/443；③ 部分接口回传原始异常字符串
（单租户风险低）；④ CSP 观察期后转正式强制；⑤ 定期轮换 `CREDENTIAL_ENCRYPTION_KEY` 并重加密。
