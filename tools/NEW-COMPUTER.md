# 在新电脑查看会话与恢复素材

仓库地址：<https://github.com/xiaoxingzi0405/001>。

**目前默认 `main` 分支保存可导出的会话记录、生成记录、素材路径清单和转移工具。图片、视频、游戏工程及分割成果的原文件仍需从保存它们的旧电脑上传。** 会话中记载的成功生成记录和旧电脑路径，不能代替原文件。下载仓库不会自动重建 Codex 的旧会话侧边栏。

## 1. 先在旧电脑上传原文件

在保存素材的旧 Mac 上按 [UPLOAD-FROM-OLD-MAC.md](UPLOAD-FROM-OLD-MAC.md) 操作。打包方法及缺失检查见 [LOCAL-TRANSFER.md](LOCAL-TRANSFER.md)。上传工具会输出备份分支链接，形如：

```text
archive/local-materials-20261004T120000Z-a1b2c3d4e5f6
```

这只是格式示例，使用工具实际输出的分支。原始素材包位于该分支的 `backups/时间-编号/`，上传工具保留 `main`。记录备份分支名称和目录名称，供新电脑使用。

在 GitHub 打开输出链接，查看 `backups/时间-编号/upload-info.json`：只有 `status` 为 `transfer_finished`，且 `expected_package_files` 与 `uploaded_package_files` 完整对应，才表示该包文件全部传输完毕。`manifest.json` 的 `missing_paths` 或 `errors` 不为空，说明旧电脑仍有文件未收集；需要找回原文件、修正来源路径并另打一个包。已传输完毕也不能证明所有历史素材都在包中。

## 2. 在新电脑下载正确分支

只看会话记录，可下载 `main`。要恢复原文件，必须选择旧电脑上传工具输出的备份分支；默认 `main` 不包含独立备份分支的素材包。

无需 Git：在仓库页面的分支下拉框选择对应备份分支，再点 **Code → Download ZIP**，完整解压到新目录。保留完整仓库目录，方便查看原始会话分页、素材清单和转移工具。

安装 Git 后，也可以克隆对应分支。以下示例中的分支名需替换为实际名称。

Mac 终端：

```bash
mkdir -p "$HOME/Projects"
git clone --single-branch --branch 'archive/local-materials-实际时间-实际编号' \
  https://github.com/xiaoxingzi0405/001.git "$HOME/Projects/001"
cd "$HOME/Projects/001"
open START-HERE.html
```

Windows PowerShell：

```powershell
git clone --single-branch --branch 'archive/local-materials-实际时间-实际编号' https://github.com/xiaoxingzi0405/001.git "$env:USERPROFILE\Documents\001"
Set-Location "$env:USERPROFILE\Documents\001"
Start-Process .\START-HERE.html
```

目标 `001` 目录应尚不存在；已有仓库可以另选新目录下载。私有仓库需要使用有权限的 GitHub 账号登录。

## 3. 显示会话数据

完整解压后，双击仓库根目录的 **`START-HERE.html`**，浏览器即可离线选择和搜索会话全文，查看生图元数据计数及消息中提到的素材路径。详细素材清单位于 `conversation-archive/local-sources.json` 和各会话的 `inventory.json`。也可以在 GitHub 上点击 `conversation-archive/` 中的 Markdown 文件查看记录。JSON 文件保留结构化数据，可在文本编辑器或程序中读取。

原始素材尚未传入时，入口只能显示已归档记录及素材索引。旧电脑 `/Users/...` 路径在新电脑上不可直接打开。图片文件恢复后，可以在对应来源目录用系统预览查看；游戏与分割工程按原工程的 README 或依赖说明运行，归档页不会自动执行工程。

## 4. 验证并恢复原始素材包

安装 Python 3.9 或更新版本；建议使用仍受维护的当前 Python 版本。恢复工具仅使用标准库。将以下 `backups/实际时间-实际编号` 替换为下载分支中真实存在的包目录。

Mac（在已下载的仓库目录运行）：

```bash
python3 tools/restore-local-materials.py \
  --bundle-dir 'backups/实际时间-实际编号' \
  --output-dir "$HOME/Desktop/001-恢复素材"
```

Windows PowerShell（在已下载的仓库目录运行）：

```powershell
py -3 .\tools\restore-local-materials.py --bundle-dir '.\backups\实际时间-实际编号' --output-dir "$env:USERPROFILE\Desktop\001-恢复素材"
```

如果使用另行传到新电脑的包，也可将 `--bundle-dir` 指向含 `manifest.json` 及**全部** `local-materials.tar.gz.part0001` 等分卷的文件夹。不要分别解压分卷。

`--output-dir` 的父目录必须存在，输出目录必须尚不存在。工具先验证每卷及完整压缩包的字节数和 SHA256，然后检查全部 tar 路径、类型、链接及文件内容；通过后才创建恢复目录，逐文件写入并再次核验实际恢复内容。它不会覆盖用户现有目录，不会写回旧电脑的绝对路径。

恢复后会出现：

```text
001-恢复素材/
  RESTORED-README.md
  RESTORED-MAP.json
  sources/
    0001-原工程目录名/
    0002-外部文件名.png
```

打开 `RESTORED-MAP.json` 的 `sources` 字段即可找到原路径、新绝对路径及相对路径的对应关系。`verified_files` 记录已恢复文件的字节数和 SHA256。原目录下的子目录关系会保留，外部指定文件放在各自编号路径下。

退出码 `0` 表示收到的包已校验恢复。旧电脑清单有缺失来源或读取错误时，工具会恢复可用部分、明确提示不完整并返回 `2`，映射状态为 `restored_available_sources_incomplete`。分卷损坏、缺失、清单不一致或不安全路径也会返回 `2`，不会留下完成的恢复目录；应重新下载或重新打包，不能将其当作全部成功。

内部符号链接只允许指向同一来源根内、已归档的普通文件或目录。外部链接、指向秘密配置的链接、缺失目标、硬链接和特殊设备会拒绝恢复。Windows 创建符号链接可能需要启用开发者模式，或使用具备该权限的终端。普通文件字节会保留；macOS 资源叉、扩展属性、ACL 与文件所有者不会恢复，包内特殊权限位也不会应用。跨平台冲突或不受支持的文件名会明确报错。

恢复工具已在 Linux 云环境用中文及空格路径、二进制文件、内外部链接、缺失来源、多分卷、损坏包和恶意 tar 夹具验证。上述 Mac/Windows 命令供相应平台使用；本次未在真实 Mac/Windows 机器执行测试。

## 5. 在新电脑用 Codex 继续任务

在 Codex 中添加或打开下载的 `001` 仓库目录，开始新任务，告诉它读取 `START-HERE.html` 和 `conversation-archive/` 的相关会话记录，并提供 `RESTORED-MAP.json` 的实际位置。要继续某个游戏或分割工程，可以直接打开恢复后的对应 `sources/编号-工程目录名`，并引用归档记录补充背景。

例如：

```text
读取此仓库的 conversation-archive 中与我的游戏相关的记录。
素材恢复映射位于 /实际新电脑路径/001-恢复素材/RESTORED-MAP.json。
根据映射找到游戏工程，检查依赖后继续开发。
```

这是使用归档内容继续新任务。旧会话记录可以浏览和引用，但不会通过克隆仓库重新出现在原应用的会话列表；应用若提供官方会话导入功能，应另按其支持的格式处理。
