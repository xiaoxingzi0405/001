# 本机原始素材转移

云环境没有挂载你的 Mac `/Users/wangye` 目录。会话中的文件路径、图片描述和生成日志不能代替原文件；本工具用于在**保存原始素材的 Mac 上**打包实际存在的文件。这里只提供打包和核验工具，没有宣称缺失的原始素材已经上传。

工具只使用 Python 3 标准库，读取 `conversation-archive/local-sources.json` 的 `source_roots` 和 `source_files` 字符串数组。目录会完整遍历，包含代码、素材、生成成果、依赖目录和构建输出；指定的外部文件也会收集。中文、空格等文件名可直接使用。路径作为 JSON 数据读取，不会执行其中的命令，也不会把 Mac 路径重定位为云端文件。

先在 Mac 下载或克隆本仓库，然后运行：

```bash
cd /你的路径/001
python3 tools/pack-local-materials.py --output-dir "$HOME/Desktop/001-本机素材包"
```

如本机项目目录与记录不同，可以追加实际目录。`--project-dir` 追加目录，仍会读取 JSON 中已记录的外部素材路径：

```bash
python3 tools/pack-local-materials.py \
  --project-dir "$HOME/Desktop/贴纸" \
  --paths-file conversation-archive/local-sources.json \
  --output-dir "$HOME/Desktop/001-本机素材包-补充"
```

输出目录必须尚不存在，工具不会覆盖旧包。输入文件和目录不会被移动、删除或修改。输出目录位于源目录内时会明确排除，防止把包自身再次收集。

输出包含按顺序拼接的 `local-materials.tar.gz.part0001` 等分卷，以及 `manifest.json`。每卷最多 24 MiB，低于 32 MiB 文件传输限制；分卷不是分别可解压的 gzip 文件。清单列出每个文件的原始路径、包内路径、字节数和 SHA256，以及各卷和完整压缩包的 SHA256。它还列出确切的 `missing_paths`、`excluded`、读取错误和去重后的来源映射。重复路径以及已经包含在工程目录内的外部文件不会重复打包。

请检查 `manifest.json` 后，把分卷和清单上传到此会话，后续即可在云端核验、还原并上传到仓库。缺失路径会保留原文，无法读取的文件会单独报告；没有可访问来源时只生成清单并返回错误码 2。`packed_available_sources` 表示可读文件已打包，不能证明所有记录中的文件都存在或已经上传。`archive.valid` 为 `false` 的失败包不可使用。

在收到分卷的机器上，以下命令按清单顺序核验并恢复完整压缩包，不需要第三方依赖。把参数替换为收到的目录：

```bash
python3 - /收到的素材包目录 <<'PY'
import hashlib
import json
import sys
from pathlib import Path

directory = Path(sys.argv[1])
manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
archive = manifest["archive"]
if not archive["valid"]:
    raise SystemExit("拒绝使用未完成的压缩包")
whole_hash = hashlib.sha256()
output = directory / "local-materials.tar.gz"
created = False
try:
    with output.open("xb") as destination:
        created = True
        for part in archive["parts"]:
            name = part["name"]
            if Path(name).name != name:
                raise ValueError("分卷名称必须是当前目录内的文件名")
            part_hash = hashlib.sha256()
            size = 0
            with (directory / name).open("rb") as source:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    part_hash.update(chunk)
                    whole_hash.update(chunk)
                    destination.write(chunk)
            if size != part["size_bytes"] or part_hash.hexdigest() != part["sha256"]:
                raise ValueError("分卷校验失败: " + name)
    if output.stat().st_size != archive["size_bytes"] or whole_hash.hexdigest() != archive["sha256"]:
        raise ValueError("完整压缩包校验失败")
except Exception:
    if created:
        output.unlink(missing_ok=True)
    raise
print("校验完成:", output)
PY
```

恢复后可先用 `tar -tzf local-materials.tar.gz` 查看文件列表，再解压到新目录。目录保存在包内独立的 `sources/编号-目录名` 下，不会写回原绝对路径。普通文件保留原字节及 tar 支持的时间、权限信息；tar 不保留 macOS 扩展属性、资源叉或 ACL。

排除规则会逐项写入清单：`.git` 元数据；`.env` 和 `.env.*` 秘密配置；明确凭证配置名称（`.netrc`、`_netrc`、`.pypirc`、`.npmrc`、`.git-credentials`、`credentials.json`、`service-account.json`、`service_account.json`、`.aws/credentials`、`.docker/config.json`、gcloud 应用默认凭证）；SSH 私钥及含标准私钥头的文件。`.env.example`、`.env.sample`、`.env.template`、`.env.dist`、`.env.defaults` 和相应后缀的模板保留。工具不会按图片扩展名、体积、构建目录或 Git 忽略规则丢弃普通素材。未知名称、嵌入普通内容的凭证需要你在本机检查后再传输。

遍历目录时不跟随符号链接。指向来源根目录外、明确被排除配置或输出目录的链接会列入排除清单；目录内链接以链接形式保存，原目标文本记在清单中。包内链接使用指向已解析内部目标的相对路径，使解压时不会引用原 Mac 绝对路径，也不会因根目录重命名而逃出来源目录。直接指定的符号链接来源也会明确排除，需在 JSON 中填写真实目录或文件路径。
