# 券商凭据的存储与安全

本页说明通过界面保存的交易凭据（Alpaca / IBKR 面板、**设置 → 券商凭据**）如何存储、接口会暴露什么、以及运营者必须保护什么。

## 存在哪、存了什么

每一条凭据在 `qd_exchange_credentials` 里占一行，按所有者隔离：

| 列 | 内容 |
|---|---|
| `user_id` | 所有者；所有读取都限定调用者自己的 id |
| `exchange_id` | `alpaca`、`binance`、`ibkr` 等 |
| `name` / `api_key_hint` | 备注名与打码提示（`PK…abcd (paper)`） |
| `encrypted_config` | 完整配置 JSON 的 **Fernet 密文** |

密文解密后的内容：

```json
{ "exchange_id": "alpaca", "api_key": "PK…", "secret_key": "…", "paper": true,
  "market_category": "USStock", "market_type": "spot" }
```

Key 与 Secret **只存在于这段密文里**——数据库中没有任何明文，提示列本身就是打码值。

## 加密方式

- **Fernet**（AES-128-CBC + HMAC-SHA256，带认证）——`app/utils/credential_crypto.py`。
- 密钥材料：`base64url(sha256(CREDENTIAL_ENCRYPTION_KEY))`。解密时也会尝试旧版 `SECRET_KEY` 派生密钥，因此老发布写入的密文仍可读；**写入一律使用 `CREDENTIAL_ENCRYPTION_KEY`**。
- `CREDENTIAL_ENCRYPTION_KEY` 位于部署用的 `.env`（根文件，挂载进容器），必须保持 `chmod 600`。

## 接口暴露面

- 凭据列表接口**只返回打码提示**，返回前会移除 `encrypted_config`。
- Alpaca/IBKR 状态接口只返回主机、模式、账户 id 与布尔值——绝不返回密钥。
- 日志中已对 provider 凭据做脱敏（见 `app/utils/redaction.py`）。

## 边界

- 只接受**官方交易所主机 + HTTPS**；用户自带 `baseUrl` 会被拒绝（`ALPACA_BASE_URL_OVERRIDE_NOT_ALLOWED`）。
- 每次读取都按 `user_id` 限定；通用凭据页有 `credentials` 权限门控（admin），券商面板需登录。
- Agent 令牌永远拿不到凭据（`C` 范围仅管理员，自助令牌不允许申请）。

## 运营清单

1. **备份 `.env`**（密码管理器或离线保险处）。`CREDENTIAL_ENCRYPTION_KEY` 是主密钥：若它与服务器一起丢失，已存凭据**不可恢复**——这正是加密的意义所在。
2. `.env.bak*` 同样要保持 `0600`：备份里可能含旧 `SECRET_KEY`，它能解密早期密文。
3. 数据库导出（pg_dump）里只有密文；仍应正常保管，但其本身不泄漏密钥材料。
4. 轮换：更换 `CREDENTIAL_ENCRYPTION_KEY` 后旧行仍可读（新→旧解密顺序），但应随后**重加密全部行**，以便彻底废弃旧密钥。
5. 交易所侧卫生：实盘 key 只开必要权限、关闭提币、优选用子账户、不再使用的 key 及时吊销。

## FAQ：为什么 Alpaca 的基础 URL 显示时不带 `/v2`？

Alpaca 文档里的端点形如 `https://paper-api.alpaca.markets/v2/account`，但 `alpaca-py` SDK 约定传**主机级** base URL、由 SDK 自己拼 API 版本：

```python
# alpaca-py RESTClient
url = base_url + "/" + version + path   # version 默认 "v2"
```

因此 `https://paper-api.alpaca.markets` + `/v2/account` 恰好得到文档中的 URL。若把 `.../v2` 传给 SDK，会拼成 `/v2/v2/account`；`normalize_base_url()` 会主动去掉用户输入里多余的尾部 `/v2`，并且不允许自定义主机。

连接失败时，界面现在会显示 Alpaca 返回的具体原因（认证失败、Key 前缀与账户模式不匹配、Key 被吊销等），而不再只有裸的 HTTP 状态码——见排障文档 `ADMIN_AND_SETTINGS_TROUBLESHOOTING_CN`。
