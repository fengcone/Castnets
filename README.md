# Castnets

Castnets 是一个 Android 优先、语音优先的“可插话播客播放器”原型。听众在播放公开 RSS
播客时暂停并提问；问题和回答被保存为锚定 `episode_id + anchor_ms` 的 Conversation
Branch。说“继续”后，客户端按服务端返回的位置恢复播放，默认回退 5 秒。

当前仓库是 M0 后端闭环，不是完整播放器。它刻意使用可审计的离线 mock 回答，不会把 AI
包装成主持人或嘉宾，也不会在没有逐句对齐信息时假装知道“刚才那一秒”说了什么。

## M0 已覆盖

- 摄取任意 HTTPS RSS 2.0 feed，保存节目、单集、音频 URL、时长和 RSS 章节时间轴。
- 列出节目和单集，并通过稳定 ID、GUID 或唯一标题选择单集。
- 导入公开但未对齐的逐字稿，或导入外部已对齐的逐句 JSON。
- 用 `chapters_only`、`transcript_unaligned`、`transcript_timed` 以及回答中的
  `precision`、`warnings` 表达信息精度。
- 在 SQLite 中持久化 Conversation Branch，支持追加追问和幂等恢复；恢复位置只计算一次。
- 无 API key、无网络时仍能返回结构化 mock 回答。词表没有覆盖的问题会明确返回
  `insufficient_context`，不会编造答案。
- 提供 loopback-only HTTP API 和由领域 dataclass 生成的 OpenAPI 3.1 契约。

## 本地运行

要求 Python 3.11+，运行时没有第三方依赖。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
```

先运行完全离线的闭环样例：

```bash
castnets --db data/demo.sqlite3 demo
castnets --db data/demo.sqlite3 podcasts
castnets --db data/demo.sqlite3 episodes --podcast 面基
castnets --db data/demo.sqlite3 branches
```

`demo` 使用仓库内的《面基》RSS 样本和一小段公开逐字稿，创建一个 “RWA 是什么意思？”
支线并恢复播放。输出里的 `mode` 必须是 `mock`。

摄取在线 RSS：

```bash
castnets --db data/castnets.sqlite3 sync
castnets --db data/castnets.sqlite3 sync --url https://example.com/podcast.xml
```

默认 feed 是《面基》：`https://feed.xyzfm.space/6hpdgggtxpxb`。开发和测试时可以用本地缓存，
`--url` 仍作为 feed 身份以及稳定 ID 的输入：

```bash
castnets --db data/castnets.sqlite3 sync \
  --url https://example.com/podcast.xml \
  --file ./cached-feed.xml
```

准备《面基》的现有公开逐字稿，或显式保持章节级精度：

```bash
castnets --db data/castnets.sqlite3 prepare "单集标题或 ID"
castnets --db data/castnets.sqlite3 prepare "单集标题或 ID" --chapters-only
```

`prepare` 只在标准化标题唯一匹配时挂接逐字稿，不根据归档序号猜测。未对齐的文本始终保留
`start_ms: null` / `end_ms: null`。

外部对齐结果可通过 `import-timed` 导入；M0 不自行实现 ASR：

```json
{
  "episode_id": "稳定的单集 ID",
  "source_url": "https://example.com/alignment.json",
  "attribution": "对齐结果的来源说明",
  "segments": [
    {
      "start_ms": 670000,
      "end_ms": 680000,
      "text": "这一段的转写文本",
      "speaker": "说话人标签或 null"
    }
  ]
}
```

```bash
castnets --db data/castnets.sqlite3 import-timed "单集标题或 ID" ./timed.json
```

## Conversation Branch CLI

```bash
castnets --db data/castnets.sqlite3 ask "单集标题或 ID" \
  --at 11:15 --question "RWA 是什么意思？"

castnets --db data/castnets.sqlite3 turn BRANCH_ID \
  --question "那 Alpha 又是什么意思？"

castnets --db data/castnets.sqlite3 resume BRANCH_ID
```

`--at` 接受秒、`MM:SS` 或 `HH:MM:SS`，支持最多三位小数。`resume` 是幂等操作：默认
`resume_position_ms = max(0, anchor_ms - 5000)`，重复调用不会继续向前减。

## Android API contract

```bash
castnets --db data/castnets.sqlite3 serve --port 8765
castnets contract > openapi.json
```

服务只监听 `127.0.0.1`，没有认证和 TLS，不能直接暴露到公网。稳定的 `/v1` 资源为：

- `GET /v1/podcasts`、`GET /v1/podcasts/{id}`
- `GET /v1/podcasts/{id}/episodes`
- `GET /v1/episodes`、`GET /v1/episodes/{id}`
- `GET /v1/episodes/{id}/content`
- `GET /v1/branches`、`GET /v1/branches/{id}`
- `POST /v1/branches`
- `POST /v1/branches/{id}/turns`
- `POST /v1/branches/{id}/resume`
- `GET /openapi.json`、`GET /health`

创建支线：

```bash
curl -sS http://127.0.0.1:8765/v1/branches \
  -H 'Content-Type: application/json' \
  -d '{"episode_id":"EPISODE_ID","anchor_ms":675000,"question":"RWA 是什么意思？"}'
```

客户端应保存服务端返回的 `branch.id`，展示 `answer.spoken_answer` / `visual_summary`，并根据
`context.precision`、`context.warnings` 和 `answer.limitations` 告知用户证据边界。恢复播放时使用
返回的 `resume_position_ms`，不要在客户端再次减 5 秒。

## 产品边界

M0 不含 Android UI、耳机按键映射、音频播放、ASR、VAD、TTS、唤醒词、说话人校正、模型
API、个人知识库或千问 AI 眼镜适配。它也不会从提问自动生成复杂知识卡片；SQLite 只保存真实
问题、时间锚点、当时使用的上下文快照、回答和来源。

上下文路由的目标是四层：个人上下文、当前单集内容、节目/主持人/嘉宾资料、通用知识。M0
只实现当前单集的章节/逐字稿检索与一个人工编写的通用演示词表，并在每条来源上标明类型。
未来模型提供方必须按问题路由所需层级，不能把四层材料无差别拼接。

更详细的取舍见 [M0 架构决策](docs/architecture-decisions.md)。
