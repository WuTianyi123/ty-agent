# ty-agent 开发进展追踪

> 记录：2026-04-22
> 下次会话开始时先读此文件了解当前状态

---

## 已完成功能

### 工具系统（Tools）
- 6 个内置文件/代码工具：read_file, write_file, patch, search_files, terminal, execute_code
- 10 个浏览器自动化工具：browser_navigate, browser_snapshot, browser_click, browser_type, browser_scroll, browser_back, browser_press, browser_get_images, browser_vision, browser_console
  - 复用 Hermes 的 agent-browser CLI（Playwright），零 API key
  - 支持 per-task session 隔离
  - 24 个测试全部通过

### CLI
- configure — 交互式配置 LLM
- setup-feishu — 扫码绑定飞书机器人
- gateway run/install/start/stop/restart/status — 网关管理
- config / set-model / test-llm

### 平台适配
- Feishu WebSocket 消息收发
- 扫码注册流程
- Markdown → Feishu post 自动转换（代码块、粗体、斜体、链接等）
- 群聊 @mention 门控
- 自身消息过滤
- 消息去重持久化（24h TTL，保存到 ~/.ty_agent/cache/feishu/seen_message_ids.json）
- 入站媒体下载：支持 image/file/audio/media，自动推断扩展名
- 出站媒体发送：send_photo / send_document 通过 Feishu 上传 API 实现

---

## 已核实问题状态

### 已修复（11个）

1. WebSocket 回调线程安全 — 使用 run_coroutine_threadsafe，不是 create_task
2. 图片下载 API 参数 — message_id 和 file_key 分开传
3. 群聊 @mention 门控 — 已实现，检查 raw_content 中是否含 @bot
4. 自身消息识别 — 检查 sender_type == "bot" 和 sender_id
5. Markdown/富文本发送 — _build_outbound_payload 检测 Markdown 语法自动发 post
6. gateway.py 路由 — 按 event.platform 查找适配器
7. 消息去重持久化 — 保存到磁盘 JSON，启动时加载，线程安全锁保护
8. 媒体下载拓展名 — 根据 Content-Type 和 filename 推断，支持 image/file/audio/media
9. Post 消息媒体标签 — 支持 img/media/file/audio/video 标签解析
10. send_photo — 上传图片到 Feishu 后发送 image 类型消息
11. send_document — 上传文件到 Feishu 后发送 file 类型消息

### 仍存在（0个）

所有已知问题已修复。

---

## 近期计划

1. ~~媒体下载支持多类型和正确扩展名~~ ✅
2. ~~完善 Post 消息解析（media/file/audio/video 标签）~~ ✅
3. ~~实现 Feishu 图片/文件上传（send_photo/send_document 覆盖）~~ ✅
4. 持续测试和稳定性改进
5. 考虑添加更多平台适配器（Telegram、Discord 等）

---

## 测试状态

37 tests passed — 24 browser + 13 feishu

---

## 技术栈

- Python 3.11 + uv
- lark-oapi（飞书 SDK）
- agent-browser CLI（Playwright，已安装在 Hermes env）
- systemd user service
