---
title: Gemini Business API Gateway
emoji: ⚡
colorFrom: blue
colorTo: purple
sdk: docker
pinned: false
license: mit
app_port: 7860
---

# Gemini Business OpenAI Gateway

OpenAI 兼容的 Gemini Business API 网关服务。

## 功能特性

- ✅ OpenAI 兼容 API (`/v1/chat/completions`)
- ✅ 多账户轮询与自动熔断
- ✅ 图片/视频生成支持
- ✅ 流式响应
- ✅ Web 管理界面

## 配置说明

需要在 Space Settings → Variables and secrets 中配置以下环境变量：

### 必需变量

| 变量名 | 说明 |
|--------|------|
| `ADMIN_KEY` | 管理后台登录密钥（必需） |

### 可选变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `API_KEY` | - | API 访问密钥（留空则无需认证） |
| `PATH_PREFIX` | - | 路径前缀（用于隐藏管理入口） |
| `PROXY` | - | HTTP 代理地址 |
| `BASE_URL` | - | 对外访问的 Base URL |

## 使用方法

1. 配置环境变量
2. 添加账户配置（通过管理界面或上传 API）
3. 使用 OpenAI 兼容客户端连接

### API 端点

```
POST /v1/chat/completions
GET  /v1/models
```

### 管理界面

- 无 PATH_PREFIX: `/admin` 或 `/login`
- 有 PATH_PREFIX: `/{PATH_PREFIX}` 或 `/{PATH_PREFIX}/login`
