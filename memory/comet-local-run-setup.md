---
name: comet-local-run-setup
description: How Comet was brought up locally — Python pin, HepAI model quirks, dev account
metadata:
  type: project
---

Comet 本机(WSL2)跑通的关键配置,2026-06-05 验证可用:

- **Python 必须钉 3.12**:`uv` 默认选 3.14,会因 pydantic-core 没有 3.14 wheel 而编译失败。`api/.python-version` 已 pin 到 3.12。
- **HepAI 的 Claude 模型当前返回 500**(`anthropic/claude-opus-4-7` 与 `claude-opus-4-7` 都不可用,服务端问题)。对话模型改用了 `openai/gpt-4o-mini`(同一 HepAI key,支持 function calling)。Claude 恢复后可在 UI 改回。
- **Embedding 用 `hepai/bge-m3:latest`**:正好 1024 维,匹配 `EMBEDDING_DIMS=1024`。HepAI 的 openai 系 embedding 是 1536/3072,不能用。
- **HepAI base_url**:`https://aiapi.ihep.ac.cn/apiv2`,provider 填 `openai`(OpenAI 兼容)。
- **开发账号**:`comet` / `comet123`,chat+embedding 模型已配并设默认。
- **Docker 权限**:dockerd 是 snap 装的,socket root:root,当前用户无权限,起存储容器需 sudo。
- 应用进程日志:后端 `/tmp/comet-api.log`、worker `/tmp/comet-worker.log`、前端 `/tmp/comet-web.log`。
- 跑通指南文档:`docs_xjq/本机跑通指南-逐行解释.md`。
