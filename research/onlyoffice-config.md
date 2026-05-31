# ONLYOFFICE 配置方案 — ClawMate

**日期**: 2026-05-29

## 原始实现（openmedia）

| 配置项 | 方式 | 位置 |
|--------|------|------|
| Document Server URL | ❌ **硬编码** | `onlyoffice.html` L64: `https://file.updatedb.online:18443/web-apps/apps/api/documents/api.js` |
| JWT Secret | 环境变量 | `OPENMEDIA_ONLYOFFICE_JWT_SECRET` |
| Public Base URL | 环境变量 | `OPENMEDIA_PUBLIC_BASE_URL` |

## ClawMate 改进方案

### 需要配置化的 4 项

| 配置项 | 说明 | 配置方式 |
|--------|------|---------|
| `onlyoffice.url` | ONLYOFFICE Document Server 地址 | `config.json` 或 `-e ONLYOFFICE_URL=` |
| `onlyoffice.jwt_secret` | JWT 签名密钥 | `config.json` 或 `-e ONLYOFFICE_JWT_SECRET=` |
| `clawmate.public_base_url` | 对外可访问的 ClawMate 地址 | `config.json` 或 `-e CLAWMATE_PUBLIC_BASE_URL=` |
| `roots` | 白名单根目录列表 | `config.json`（同之前版本） |

### 推荐配置方式

```json
{
  "roots": [
    {"id": "Openclaw", "label": "Media", "dir": "/home/openclaw/.openclaw/media"},
    {"id": "webprojects", "label": "Projects", "dir": "/home/openclaw/webprojects"}
  ],
  "defaultRootId": "Openclaw",
  "onlyoffice": {
    "url": "https://onlyoffice.example.com",
    "jwt_secret": "your-secret-here"
  },
  "public_base_url": "https://clawmate.example.com"
}
```

### Docker Compose 示范

```yaml
services:
  onlyoffice:
    image: onlyoffice/documentserver:latest
    environment:
      - JWT_ENABLED=true
      - JWT_SECRET=${ONLYOFFICE_JWT_SECRET}
    ports:
      - "8080:80"

  clawmate:
    image: clawmate:latest
    environment:
      - CLAWMATE_ONLYOFFICE_URL=http://onlyoffice:80
      - CLAWMATE_ONLYOFFICE_JWT_SECRET=${ONLYOFFICE_JWT_SECRET}
      - CLAWMATE_PUBLIC_BASE_URL=http://localhost:3000
    volumes:
      - ./config.json:/app/config.json
      - /home/openclaw:/data/openclaw
    ports:
      - "3000:3000"
```

### 关键变化 vs openmedia

| 项目 | openmedia | ClawMate |
|------|-----------|----------|
| ONLYOFFICE URL | 硬编码 HTML | 配置文件可指定 |
| JWT Secret | 仅环境变量 | 环境变量 + config.json |
| 无 ONLYOFFICE 时 | 功能不可用（不报错） | 优雅降级，Office 文件提供下载 |
