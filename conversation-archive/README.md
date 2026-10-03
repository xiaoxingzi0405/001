# 游戏、生图、分割会话记录归档

这是 9 个选定会话在导出时可读取的记录快照，**不是完整素材备份**。已保存原始 API 响应、去重整理后的对话、路径和生图元数据；实际工程、视频、参考素材、贴纸、分割结果和生成图片二进制均未取得，仍待从你的 Mac 补齐。

导出截至 UTC **2026-10-03T16:14:50+00:00**，对应上海时间 **2026-10-04T00:14:50+08:00**。正在运行的会话可能在此后继续产生新内容。

| 原会话 | 已归档 | 会话 ID | 页 / 补充窗口 | 去重消息 | 成功生图记录 | 原素材二进制 |
| --- | --- | --- | --- | ---: | ---: | --- |
| [游戏1号](threads/01a0fbd7-4d8a-7220-a2c1-0487662562c2/conversation.md) | 否 | `01a0fbd7-4d8a-7220-a2c1-0487662562c2` | 21 / 21 | 192 | 11 | 0，未取得 |
| [游戏2号](threads/01a0fe5e-185b-7f20-917e-d6558aafc741/conversation.md) | 否 | `01a0fe5e-185b-7f20-917e-d6558aafc741` | 8 / 8 | 49 | 10 | 0，未取得 |
| [游戏2号](threads/01a0fe5a-9c61-7391-b8a3-3a6c45a47f8b/conversation.md) | 是 | `01a0fe5a-9c61-7391-b8a3-3a6c45a47f8b` | 1 / 1 | 4 | 0 | 0，未取得 |
| [游戏3号](threads/01a0ff53-d4ce-7223-9893-2c65418ffa2d/conversation.md) | 否 | `01a0ff53-d4ce-7223-9893-2c65418ffa2d` | 5 / 5 | 59 | 23 | 0，未取得 |
| [生图1号](threads/01a0fd6e-3a20-7be0-b98f-6ea35299628c/conversation.md) | 否 | `01a0fd6e-3a20-7be0-b98f-6ea35299628c` | 13 / 13 | 124 | 70 | 0，未取得 |
| [生图2号](threads/01a0fe6a-db08-7a60-b448-d6689edfd31a/conversation.md) | 否 | `01a0fe6a-db08-7a60-b448-d6689edfd31a` | 5 / 5 | 35 | 13 | 0，未取得 |
| [分割1号](threads/01a0fbff-d08a-7711-9289-3207ba7d5f78/conversation.md) | 否 | `01a0fbff-d08a-7711-9289-3207ba7d5f78` | 11 / 11 | 137 | 48 | 0，未取得 |
| [分割2号](threads/01a0fdbd-87ca-7fe3-85eb-c71bf1dc0620/conversation.md) | 否 | `01a0fdbd-87ca-7fe3-85eb-c71bf1dc0620` | 3 / 3 | 32 | 28 | 0，未取得 |
| [分割3号](threads/01a0fe67-aeca-70b1-a1cb-6834350c2059/conversation.md) | 否 | `01a0fe67-aeca-70b1-a1cb-6834350c2059` | 4 / 4 | 33 | 5 | 0，未取得 |

原会话标题原样保留；同名“游戏2号”通过“已归档”列及会话 ID 区分。成功生图记录统计仅指去重后 `imageGeneration` 的 `completed` 状态记录，**不是图片文件数量或已上传成果数量**。

每个会话目录中的 `pages/` 是分页响应，`windows/`（如有）是补充读取响应，`conversation.md` 是整理后的可读记录。`summary.json` 保存计数、截断、空记录、缺失工具输出和完整性限制，`inventory.json` 保存路径与成果元数据。详细证据请从 [index.json](index.json) 中的 `summary_path` 查阅对应摘要。

读取 API 的单项文本请求上限为 **20,000 字符**，每次响应仍有返回范围和长度限制。补充窗口和分页只能保存 API 实际返回的内容；即使分页耗尽，也不能保证原始日志全文、历史工具输出或未返回项目完整。`completed`、`savedPath`、文件名或命令日志都不能代替实际图片和工程文件。

[source-threads.json](source-threads.json) 保存选定会话来源；[local-sources.json](local-sources.json) 保存需在 Mac 收集的明确来源目录和附件路径。来源列表不从任意工具命令盲抓路径，也不会把 `/Users/wangye` 路径映射成云端已存在文件。

按 [本机原始素材转移说明](../tools/LOCAL-TRANSFER.md) 在保存原文件的 Mac 上运行打包工具，检查缺失项和排除项，再把分卷及清单传入。当前归档中实际素材二进制为 **0**，全部图片和工程仍待补齐。
