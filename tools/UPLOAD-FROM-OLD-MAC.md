# 从保存素材的旧 Mac 直接上传

在**仍保存游戏工程、图片、视频和分割成果的旧 Mac**运行工具。云环境无法读取旧 Mac 的 `/Users/wangye`，会话中的路径与成功生图记录不等于原始文件已经备份。

先下载或克隆此仓库。终端进入 `001` 目录后，只需运行：

```bash
python3 tools/upload-local-materials.py
```

需要 Python 3、Git，以及该 Mac 已有的 GitHub 仓库读写授权。工具沿用 Git 的 HTTPS 凭证助手与提交签名设置，不读取或输出 token，不要求安装 Python 依赖。若授权失败，先通过已有的 GitHub / Git 安全登录方式连接账号，再续传；不要把凭证发到聊天中。

工具读取 `conversation-archive/local-sources.json`，收集真实存在的工程目录、附件和生图成果。新增或移过位置的工程可以追加：

```bash
python3 tools/upload-local-materials.py --project-dir "$HOME/Desktop/贴纸"
```

它先生成清单和最多 24 MiB 的压缩分卷，再使用独立临时克隆，将文件上传到仓库的新分支 `archive/local-materials-时间-随机编号`、目录 `backups/时间-随机编号/`。每批新增数据低于 128 MiB，默认上限为 120 MiB；每批提交后立即推送，避免一次推送全部大文件。现有 `main`、旧 Mac 源文件和已有本地仓库改动都保留。工具最后打印可直接打开的 GitHub 分支链接。

`.env`、Git 凭证、私钥等敏感配置由打包工具排除，原因记录在 `manifest.json`。目录内依赖、构建成果和普通素材会收集。输出目录本身排除，上传克隆只在打包完成后创建。

清单逐项记录 `missing_paths`、`excluded`、`errors` 以及每个文件和分卷的 SHA256。缺失路径仍会报告；上传完可读素材并不代表不存在的文件已上传。退出码 `0` 表示有文件的有效包已上传且无缺失和读取错误，`2` 表示可读资料或报告已上传，但有缺失、读取错误或没有有效文件；`1` 表示上传中断。`upload-info.json` 记录应有文件与当前批次，可判断一个分支是否仅上传了一部分。

网络或授权问题发生时，已上传的批次保留。终端会打印本机 `_upload-state.json` 的路径；保留它及同目录的分卷、`repository`，不要删除或修改该目录。恢复网络或授权后运行：

```bash
python3 tools/upload-local-materials.py --resume "/终端打印的目录/_upload-state.json"
```

续传使用原分支和原包，不改写分支历史，也不会重新打包。若要补充此前缺失且现在找回的素材，运行新的上传命令，生成另一份有独立编号的备份。默认工作目录位于系统临时目录；长时间保留续传资料时，可以在首次运行用 `--work-dir "/新的保存目录"` 指定尚不存在的目录。

## 在新电脑查看

会话记录位于仓库的 `conversation-archive`，可以直接在 GitHub 查看或克隆到新电脑；下载后打开根目录 `START-HERE.html` 阅读可读取的会话、生图元数据计数和记录中的素材路径。原始素材完成上传后，需要选择工具打印的备份分支下载，或用 `git clone --single-branch --branch "工具打印的分支名" https://github.com/xiaoxingzi0405/001.git` 克隆；只下载 `main` 不包含独立备份分支的原始素材。

进入下载后的仓库目录，按打印的编号运行恢复工具，核验、拼接、解压，并生成 `RESTORED-README.md` 和新旧路径映射。恢复后用新电脑的系统预览器打开图片和视频：

```bash
python3 tools/restore-local-materials.py --bundle-dir "backups/工具打印的编号" --output-dir "$HOME/Desktop/001-恢复素材"
```

分卷不能单独解压。完整新电脑说明见 [NEW-COMPUTER.md](NEW-COMPUTER.md)。

## 离线验证

工具仅支持默认目标 `https://github.com/xiaoxingzi0405/001.git` 或 `--remote /绝对路径/本地bare仓库`。本地 bare 参数用于测试，不能用带 token 的 URL 替换认证。`--part-size-mib` 与 `--batch-size-mib` 可以调小以验证多批次续传；所有测试都应明确传入本地 bare 地址，避免上传测试文件到真实 GitHub。
