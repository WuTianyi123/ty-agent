# ty-agent Feishu 适配器专项审查报告

审查文件：
- `ty_agent/platforms/feishu.py`
- `ty_agent/gateway.py`
- `ty_agent/platforms/base.py`

参考实现：
- `hermes-agent/gateway/platforms/feishu.py`

---

## 一、严重问题（必须修复）

### 1. WebSocket 回调线程安全问题（崩溃级）

**位置**：`ty_agent/platforms/feishu.py:454`

```python
asyncio.create_task(self._handle_message(event))
```

`lark_oapi` 的 SDK 在后台线程中调用 `_on_message` 回调。在此线程中直接调用 `asyncio.create_task()` 会因为不存在运行中的事件循环而抛出 `RuntimeError`。参考实现使用 `asyncio.run_coroutine_threadsafe(coro, loop)` 并持有 `self._loop` 引用，将事件安全地投递到适配器的主事件循环。

**修复建议**：在 `start()` 中保存 `asyncio.get_running_loop()`，回调里使用 `run_coroutine_threadsafe` 调度。

---

### 2. 图片下载 API 参数错误（功能不可用）

**位置**：`ty_agent/platforms/feishu.py:471`

```python
req = GetMessageResourceRequest.builder().message_id(image_key).file_key(image_key).build()
```

`GetMessageResourceRequest` 的 `message_id` 必须是收到消息事件中的 `message_id`，`file_key` 才是 `image_key`。ty-agent 把 `image_key` 同时传给了两个字段，导致 API 调用必然失败，所有入站图片都无法下载。

**参考实现**：
```python
request = self._build_message_resource_request(
    message_id=message_id, file_key=image_key, resource_type="image"
)
```

---

### 3. 群聊缺少 @mention 门控（洪水级）

**位置**：`ty_agent/platforms/feishu.py:414-418`

```python
text = re.sub(rf"<at user_id=\"{self._bot_open_id}\">.*?</at>", "", text).strip()
```

ty-agent 仅把 @bot 的文本删掉，但**不会拒绝非 @mention 的群聊消息**。这意味着机器人在群聊里会对每一条消息做出回复，造成消息洪水。参考实现有 `_should_accept_group_message()`，它要求：
1. 通过 allowlist/blacklist/open/admin_only 策略检查；
2. 消息必须 @bot 或 @_all；
3. 对 `im.message.receive_v1` 的 `mentions` 列表做精确匹配。

**修复建议**：在 `_on_message` 中增加群聊门控逻辑，仅当消息明确 @bot 时才处理。

---

### 4. 没有识别自身发送的消息（回声/循环风险）

**位置**：`ty_agent/platforms/feishu.py:432-433`

```python
if sender_id == self._bot_open_id:
    return
```

ty-agent 仅通过 `sender_id` 的 `open_id` 判断是否为自己发送的消息。参考实现使用 `_is_self_sent_bot_message()`，它会检查：
- `sender_type` 是否为 `"bot"` 或 `"app"`；
- `sender_id.open_id` 或 `sender_id.user_id` 是否匹配。

在 Feishu 中，bot 发送的消息 `sender_type` 是 `"bot"`，而 `sender_id` 的 `open_id` 可能与 `self._bot_open_id` 不一致（取决于事件格式）。仅靠 `sender_id` 可能导致漏判，进而引发回声循环。

---

## 二、重要缺陷（应该修复）

### 5. 消息去重不可持久化，且清理效率低

**位置**：`ty_agent/platforms/feishu.py:456-466`

- ty-agent 的去重使用纯内存字典 `self._dedup`，**进程重启后完全失效**，会导致重新处理旧消息。
- 每次检查重复时做完整字典推导式清理（`{k: v for k, v in self._dedup.items() if v > cutoff}`），时间复杂度 O(n)。

**参考实现**：
- 使用 `_dedup_state_path` 持久化到 JSON；
- 使用 `OrderedDict` + `deque` 实现 LRU 淘汰（容量上限 2048）；
- 每次去重只读写磁盘一次，且有 TTL 过滤。

**修复建议**：将去重状态持久化到 `~/.ty_agent/feishu_seen_message_ids.json`，使用 OrderedDict/LRU 结构。

---

### 6. 媒体下载实现严重不足

**位置**：`ty_agent/platforms/feishu.py:468-481`

| 问题 | 说明 |
|------|------|
| 扩展名硬编码 | 所有图片强制保存为 `.png`，不根据 `Content-Type` 判断实际格式（可能是 `.jpg`、`.webp`） |
| 仅支持图片 | 完全不支持 `file`、`audio`、`media`、`video` 类型下载 |
| 同步阻塞 | 使用同步 SDK 方法 `self._client.im.v1.message_resource.get(req)`，阻塞后台线程 |
| 缺少 Content-Type 解析 | 不读取响应头中的 `Content-Type`，不设置正确的 `media_type` |
| 缺少错误恢复 | 对 `resource_type` 只做一次尝试；参考实现会尝试 `image` -> `file` 回退 |

**修复建议**：
1. 使用 `asyncio.to_thread()` 或线程池包装同步下载；
2. 根据响应头推断扩展名；
3. 增加 `file`、`audio`、`video` 的下载路径；
4. 将下载结果存入正确的缓存目录并返回 MIME 类型。

---

### 7. 消息解析不完善

**位置**：`ty_agent/platforms/feishu.py:591-609`

`_extract_post_text()` 只处理了：
- `tag == "text"`：提取文本
- `tag == "a"`：提取链接
- `tag == "at"`：提取 @提及

**缺少**：
- `tag == "img"` / `"image"`：图片元素（应收集 `image_key` 供下载）
- `tag == "media"` / `"file"` / `"audio"` / `"video"`：媒体附件
- `tag == "code_block"` / `"pre"`：代码块
- `tag == "code"`：行内代码
- `tag == "br"`、`"hr"`、`"divider"`：换行/分割线
- `tag == "emotion"` / `"emoji"`：表情
- 嵌套结构递归遍历（`children`、`elements`）
- 多 locale 回退（仅遍历 `zh_cn`、`en_us`、`ja_jp`，没有兜底所有 key）

参考实现的 `parse_feishu_post_payload()` + `_render_post_element()` 覆盖了以上全部情况，并且返回 `FeishuPostParseResult`，包含 `image_keys`、`media_refs`、`mentioned_ids`。

---

### 8. 发送消息不支持 Markdown/富文本

**位置**：`ty_agent/platforms/feishu.py:526-568`

`send_message()` 永远发送 `msg_type="text"`，不对 Markdown 语法做任何转换。当 LLM 返回包含代码块、列表、链接等 Markdown 内容时，在 Feishu 中会以纯文本形式呈现，可读性极差。

**参考实现**：`_build_outbound_payload()` 会检测 Markdown 语法（`_MARKDOWN_HINT_RE`），自动将内容转换为 Feishu `post` 类型（富文本消息），使用 `md` tag 渲染代码块、粗体、斜体、链接等。

**修复建议**：实现 `_build_markdown_post_payload()` 并在 `send_message()` 中根据内容自动选择 `text` 或 `post`。

---

### 9. gateway.py 的 `_find_adapter_for_event` 逻辑错误

**位置**：`ty_agent/gateway.py:109-114`

```python
for adapter in self.adapters.values():
    return adapter
```

这段代码无论 event 来自哪个平台，永远返回字典中的第一个适配器。虽然目前只有 Feishu 一个平台，但这是一个明显的逻辑缺陷，未来加入其他平台后会导致事件路由错误。

**修复建议**：在 `MessageEvent` 中增加 `platform_name` 字段，或在适配器内部保存来源映射，根据事件属性正确查找适配器。

---

### 10. 缺少 WebSocket 自动重连机制

**位置**：`ty_agent/platforms/feishu.py:485-514`

`start()` 直接调用 `self._ws_client.start()`，一旦连接断开（网络抖动、服务端重启），适配器会直接退出，依赖 gateway 的 5 秒重试重启整个适配器。这会导致：
- 未处理的消息丢失；
- 状态（去重缓存、session）全部重置。

**参考实现**：
- 在 SDK 的 WS client 上设置 `_auto_reconnect = True`；
- 自定义 `_reconnect_nonce` 和 `_reconnect_interval`；
- 有 `pending_inbound_events` 队列在重连期间缓存事件。

---

### 11. 没有 `send_photo` / `send_document` 的真正实现

**位置**：`ty_agent/platforms/base.py:141-167`

基类中的 `send_photo` 和 `send_document` 只发送文本路径，ty-agent 的 FeishuAdapter 没有覆盖它们。当 agent 需要发送图片或文件给用户时（例如工具生成的截图），会以纯文本形式发送路径，用户无法直接查看。

**参考实现**：FeishuAdapter 实现了 `send_document()`、`send_image_file()`、`send_audio()`、`send_video()`，使用 Feishu 的上传 API（`CreateImageRequest`、`CreateFileRequest`）发送原生附件。

---

## 三、轻微建议（可选）

### 12. 扫码注册流程可以优化
- `_poll_registration` 使用固定间隔轮询，建议参考实现加入指数退避；
- `probe_bot` 使用 `urlopen` 同步请求，可考虑改为 `asyncio.to_thread`；
- 注册成功后的 `app_name` 字段没有保存，可以存入配置。

### 13. 会话密钥（session key）粒度
`build_session_key` 在群聊中使用了 `sender_id`，这是正确的（与参考实现一致）。但如果未来需要支持“群聊中所有人共享一个会话”，建议增加 `group_sessions_per_user` 配置项。

### 14. 日志和监控
- 缺少对发送失败的分类日志（参考实现区分了 `retryable` 错误和非重试错误）；
- 没有 webhook 异常检测计数器；
- 没有处理状态反馈（如 Typing 反应）。

### 15. 其他遗漏的参考功能（非必需，但值得了解）
- Webhook 模式（HTTP 事件推送）
- 消息已读事件（`im.message.message_read_v1`）
- 消息撤回事件（`im.message.recalled_v1`）
- 表情反应事件路由为合成文本事件
- 卡片按钮点击事件（审批/交互）
- 执行审批卡片（exec approval）
- 文本/媒体消息批处理（batching）
- 发送消息时的分片/长度限制处理
- 速率限制和重试退避

---

## 四、总体评价

**ty-agent 的 Feishu 适配器是一个功能骨架，实现了最基础的 WebSocket 连接、文本收发和扫码注册，但距离生产可用还有明显差距。**

| 维度 | 评分 | 说明 |
|------|------|------|
| 扫码注册 | ★★★☆☆ | 流程正确，但缺少持久化和自动域名切换后的配置保存 |
| WebSocket 连接 | ★★☆☆☆ | 能连上，但线程安全有严重bug，无自动重连，无事件队列 |
| 消息去重 | ★★☆☆☆ | 内存实现，重启失效，无持久化 |
| 媒体下载 | ★☆☆☆☆ | API参数错误导致功能不可用，仅支持图片，无MIME解析 |
| 消息解析 | ★★☆☆☆ | 基础文本/链接/@能解析，但Post类型解析不完整，缺少多媒体元素 |
| 群聊/私聊管理 | ★★☆☆☆ | session key 逻辑基本正确，但缺少群聊@mention门控，缺少用户策略 |
| 与参考实现对比 | 大量遗漏 | 缺少Webhook、Markdown发送、媒体发送、反应事件、卡片交互、批处理等 |

**最优先修复的 3 件事**：
1. 修复 WebSocket 回调中的 `asyncio.create_task` 线程安全问题（使用 `run_coroutine_threadsafe`）；
2. 修复 `_download_image` 的 `message_id` 参数传递错误；
3. 增加群聊 @mention 门控，避免群聊消息洪水。
