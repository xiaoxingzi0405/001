# 001
贴纸

下载并解压仓库后，双击根目录的 **START-HERE.html**，可以离线选择和搜索 9 个游戏、生图、分割会话。

[会话记录归档](conversation-archive/README.md)包含可读取的消息、素材路径清单及成功生图元数据。原始图片、视频、游戏工程和分割成果仍需从保存它们的旧 Mac 上传；当前记录归档不是完整素材备份。

在旧 Mac 下载最新仓库并进入解压目录后，运行：

```bash
python3 tools/upload-local-materials.py
```

工具会打包实际存在的文件并推送独立备份分支，打印分支链接和缺失报告。新电脑需要下载该备份分支，校验、恢复原始文件后才能查看图片和工程。克隆仓库不会自动重建 Codex 的旧会话列表。

[旧 Mac 上传说明](tools/UPLOAD-FROM-OLD-MAC.md) · [新电脑查看与恢复](tools/NEW-COMPUTER.md) · [手动打包与分卷转移](tools/LOCAL-TRANSFER.md)
