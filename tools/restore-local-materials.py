#!/usr/bin/env python3
"""Verify a local-materials bundle and restore it into a new directory safely."""

import argparse
import hashlib
import json
import math
import os
import posixpath
import re
import shutil
import stat
import sys
import tarfile
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


CHUNK = 1024 * 1024
TEMPLATE_SUFFIXES = (".example", ".sample", ".template", ".dist", ".defaults")
CREDENTIAL_NAMES = {
    ".netrc", "_netrc", ".pypirc", ".npmrc", ".git-credentials",
    "credentials.json", "service-account.json", "service_account.json",
}
PRIVATE_KEY_HEADERS = (
    b"-----BEGIN PRIVATE KEY-----", b"-----BEGIN ENCRYPTED PRIVATE KEY-----",
    b"-----BEGIN RSA PRIVATE KEY-----", b"-----BEGIN EC PRIVATE KEY-----",
    b"-----BEGIN DSA PRIVATE KEY-----", b"-----BEGIN OPENSSH PRIVATE KEY-----",
)


class RestoreError(ValueError):
    pass


def fail(message):
    raise RestoreError(message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            fail("清单包含重复 JSON 字段: {}".format(key))
        result[key] = value
    return result


def nonnegative(value, label):
    if type(value) is not int or value < 0:
        fail("{} 必须为非负整数".format(label))
    return value


def digest(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        fail("{} 必须为 SHA256".format(label))
    return value.lower()


def path_name(value):
    """Use the same strict relative spelling on Unix and Windows."""
    if not isinstance(value, str) or not value or "\\" in value or "\0" in value:
        fail("无效包内路径: {!r}".format(value))
    parts = value.split("/")
    if any(not part or part in (".", "..") for part in parts):
        fail("包内路径必须为规范相对路径: {!r}".format(value))
    for part in parts:
        stem = part.split(".", 1)[0].casefold()
        if (any(char in part for char in ':<>"|?*') or part.endswith((".", " ")) or
                stem in {"con", "prn", "aux", "nul"} or
                re.fullmatch(r"(?:com|lpt)[1-9¹²³]", stem) or
                any(ord(char) < 32 for char in part)):
            fail("无法安全跨平台恢复的文件名: {!r}".format(value))
    if len(parts) < 2 or parts[0] != "sources":
        fail("所有素材必须位于 sources/来源目录 下: {!r}".format(value))
    return value


def alias_key(value):
    return unicodedata.normalize("NFC", value).casefold()


def exclusion_reason(value):
    # The numbered source root replaces its original basename in the archive.
    names = [component.lower() for component in PurePosixPath(value).parts]
    if len(names) >= 2:
        names[1] = re.sub(r"^\d+-", "", names[1])
    name = names[-1]
    if ".git" in names:
        return "Git 元数据"
    if name == ".env" or (name.startswith(".env.") and not name.endswith(TEMPLATE_SUFFIXES)):
        return "环境秘密配置"
    if name in CREDENTIAL_NAMES:
        return "凭证配置"
    if len(names) >= 2:
        if tuple(names[-2:]) in ((".aws", "credentials"), (".docker", "config.json"),
                                ("gcloud", "application_default_credentials.json")):
            return "凭证配置"
        if names[-2] == ".ssh" and name.startswith("id_") and not name.endswith(".pub"):
            return "SSH 私钥"
    return None


def regular_input(path):
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        fail("输入必须为普通文件，不能是符号链接: {}".format(path))
    descriptor = os.open(str(path), os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
    handle = os.fdopen(descriptor, "rb")
    after = os.fstat(handle.fileno())
    if not stat.S_ISREG(after.st_mode) or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
        handle.close()
        fail("输入文件在打开时改变: {}".format(path))
    return handle


def read_manifest(bundle):
    with regular_input(bundle / "manifest.json") as handle:
        manifest = json.load(handle, object_pairs_hook=unique_object)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        fail("不支持的 manifest.json 格式")
    archive = manifest.get("archive")
    if not isinstance(archive, dict) or archive.get("valid") is not True or archive.get("format") != "tar.gz":
        fail("拒绝未完成或无效的压缩包")
    for field in ("entries", "requested_sources", "missing_paths", "excluded", "errors"):
        if not isinstance(manifest.get(field), list):
            fail("清单缺少数组字段: {}".format(field))
    if not isinstance(archive.get("parts"), list) or not archive["parts"]:
        fail("清单没有分卷")
    nonnegative(archive.get("size_bytes"), "完整压缩包字节数")
    digest(archive.get("sha256"), "完整压缩包哈希")
    for index, part in enumerate(archive["parts"], 1):
        if not isinstance(part, dict) or part.get("name") != "local-materials.tar.gz.part{:04d}".format(index):
            fail("分卷必须按连续编号列出，且名称不得包含目录")
        nonnegative(part.get("size_bytes"), "分卷字节数")
        digest(part.get("sha256"), "分卷哈希")
    if sum(part["size_bytes"] for part in archive["parts"]) != archive["size_bytes"]:
        fail("清单内分卷总字节数与完整压缩包不一致")
    return manifest


def combine_parts(bundle, manifest, archive_path):
    whole_hash = hashlib.sha256()
    whole_size = 0
    with archive_path.open("xb") as destination:
        for part in manifest["archive"]["parts"]:
            part_hash = hashlib.sha256()
            size = 0
            with regular_input(bundle / part["name"]) as source:
                while True:
                    chunk = source.read(CHUNK)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > part["size_bytes"]:
                        fail("分卷字节数超出清单: {}".format(part["name"]))
                    part_hash.update(chunk)
                    whole_hash.update(chunk)
                    destination.write(chunk)
            if size != part["size_bytes"] or part_hash.hexdigest() != digest(part["sha256"], "分卷哈希"):
                fail("分卷校验失败: {}".format(part["name"]))
            whole_size += size
    archive = manifest["archive"]
    if whole_size != archive["size_bytes"] or whole_hash.hexdigest() != digest(archive["sha256"], "完整压缩包哈希"):
        fail("完整压缩包校验失败")


def index_manifest(manifest):
    roots = {}
    for source in manifest["requested_sources"]:
        if not isinstance(source, dict):
            fail("无效来源记录")
        if source.get("status") == "available":
            root = path_name(source.get("archive_path"))
            if len(root.split("/")) != 2 or root in roots or source.get("kind") not in ("file", "directory"):
                fail("无效或重复来源根目录: {}".format(root))
            roots[root] = source
    if not roots:
        fail("清单没有可恢复的来源")
    entries = {}
    aliases = {}
    for entry in manifest["entries"]:
        if not isinstance(entry, dict):
            fail("无效素材记录")
        name = path_name(entry.get("archive_path"))
        root = "/".join(name.split("/")[:2])
        if root not in roots:
            fail("素材没有对应的来源根目录: {}".format(name))
        alias = alias_key(name)
        if name in entries or alias in aliases:
            fail("重复路径或跨平台名称冲突: {}".format(name))
        aliases[alias] = name
        kind = entry.get("type")
        if kind not in ("file", "directory", "symlink"):
            fail("不支持的素材类型: {}".format(name))
        reason = exclusion_reason(name)
        if reason:
            fail("包内包含应排除的{}: {}".format(reason, name))
        if kind == "file":
            nonnegative(entry.get("size_bytes"), "素材字节数")
            digest(entry.get("sha256"), "素材哈希")
        entries[name] = entry
    for root, source in roots.items():
        if root not in entries or entries[root]["type"] != source["kind"]:
            fail("来源根目录缺失或类型不一致: {}".format(root))
    for name, entry in entries.items():
        parent = posixpath.dirname(name)
        while parent != "sources":
            if parent not in entries or entries[parent]["type"] != "directory":
                fail("素材父目录缺失或不是普通目录: {}".format(name))
            parent = posixpath.dirname(parent)
        if entry["type"] == "symlink":
            target = entry.get("archive_target")
            if (not isinstance(target, str) or not target or "\\" in target or "\0" in target or
                    target.startswith("/") or ":" in target):
                fail("无效符号链接目标: {}".format(name))
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
            path_name(resolved)
            root = "/".join(name.split("/")[:2])
            if resolved != root and not resolved.startswith(root + "/"):
                fail("符号链接逃出来源根目录: {}".format(name))
            if exclusion_reason(resolved):
                fail("符号链接指向排除的秘密配置: {}".format(name))
            # The packer resolves internal targets before writing the archive;
            # dangling targets and chains cannot prove a complete restoration.
            if resolved not in entries or entries[resolved]["type"] not in ("file", "directory"):
                fail("符号链接目标缺失或不是普通文件/目录: {}".format(name))
            entry = dict(entry, resolved_target=resolved)
            entries[name] = entry
    return roots, entries


def hash_stream(handle):
    result = hashlib.sha256()
    size = 0
    prefix = b""
    while True:
        chunk = handle.read(CHUNK)
        if not chunk:
            break
        if len(prefix) < 256:
            prefix += chunk[:256 - len(prefix)]
        result.update(chunk)
        size += len(chunk)
    return size, result.hexdigest(), prefix


def check_archive(archive_path, entries):
    """Inspect all names, types, links and file bytes before any restoration."""
    members = {}
    with tarfile.open(archive_path, mode="r:gz", ignore_zeros=True) as archive:
        for member in archive:
            name = path_name(member.name)
            if name in members:
                fail("压缩包包含重复路径: {}".format(name))
            if name not in entries:
                fail("压缩包包含清单外素材: {}".format(name))
            entry = entries[name]
            if not math.isfinite(member.mtime):
                fail("条目时间无效: {}".format(name))
            if member.isreg():
                kind = "file"
            elif member.isdir():
                kind = "directory"
            elif member.issym():
                kind = "symlink"
            else:
                fail("拒绝硬链接、设备或其他特殊 tar 条目: {}".format(name))
            if kind != entry["type"]:
                fail("素材类型与清单不一致: {}".format(name))
            if kind == "symlink" and member.linkname != entry["archive_target"]:
                fail("符号链接目标与清单不一致: {}".format(name))
            if kind != "file" and member.size != 0:
                fail("非文件条目包含意外字节: {}".format(name))
            if kind == "file":
                if member.size != entry["size_bytes"]:
                    fail("素材字节数与清单不一致: {}".format(name))
                with archive.extractfile(member) as handle:
                    size, sha256, prefix = hash_stream(handle)
                if size != entry["size_bytes"] or sha256 != digest(entry["sha256"], "素材哈希"):
                    fail("压缩包内素材校验失败: {}".format(name))
                if any(header in prefix for header in PRIVATE_KEY_HEADERS):
                    fail("包内含私钥内容，拒绝恢复: {}".format(name))
            members[name] = member
    missing = sorted(set(entries) - set(members))
    if missing:
        fail("压缩包缺少清单素材: {}".format(", ".join(missing[:5])))
    return members


def destination(output, name):
    # Only prevalidated names enter here; no tar library extraction is used.
    path = output.joinpath(*name.split("/"))
    if not path.is_relative_to(output):
        fail("恢复路径越界: {}".format(name))
    return path


def write_restoration(archive_path, output, roots, entries, members, manifest):
    (output / "sources").mkdir()
    for name, entry in sorted(entries.items(), key=lambda item: (item[0].count("/"), item[0])):
        if entry["type"] == "directory":
            destination(output, name).mkdir()
    with tarfile.open(archive_path, mode="r:gz") as archive:
        for name, entry in entries.items():
            if entry["type"] != "file":
                continue
            path = destination(output, name)
            with archive.extractfile(members[name]) as source, path.open("xb") as target:
                shutil.copyfileobj(source, target, CHUNK)
            with regular_input(path) as handle:
                size, sha256, _ = hash_stream(handle)
            if size != entry["size_bytes"] or sha256 != digest(entry["sha256"], "素材哈希"):
                fail("实际恢复文件校验失败: {}".format(name))
    for name, entry in entries.items():
        if entry["type"] == "symlink":
            target_is_directory = entries[entry["resolved_target"]]["type"] == "directory"
            try:
                os.symlink(entry["archive_target"], destination(output, name), target_is_directory=target_is_directory)
            except OSError as error:
                fail("无法创建内部符号链接 {}；Windows 请启用开发者模式或使用具备创建链接权限的终端。{}".format(name, error))
    incomplete = bool(manifest["missing_paths"] or manifest["errors"])
    report = {
        "schema_version": 1,
        "restored_at": datetime.now(timezone.utc).isoformat(),
        "status": "restored_available_sources_incomplete" if incomplete else "restored_verified_bundle",
        "scope": "此状态仅描述已收到的素材包，不证明所有历史会话素材均已提供。",
        "archive_sha256": manifest["archive"]["sha256"],
        "sources": [dict(source, restored_relative_path=root,
                         restored_path=str(destination(output, root))) for root, source in roots.items()],
        "requested_sources": manifest["requested_sources"],
        "missing_paths": manifest["missing_paths"],
        "excluded": manifest["excluded"],
        "errors": manifest["errors"],
        "verified_files": [dict(entry, restored_relative_path=name) for name, entry in entries.items()
                           if entry["type"] == "file"],
    }
    with (output / "RESTORED-MAP.json").open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    with (output / "RESTORED-README.md").open("x", encoding="utf-8") as handle:
        handle.write("# 已恢复素材\n\n")
        handle.write("分卷、完整压缩包和实际恢复文件的字节数及 SHA256 已通过核验。\n\n")
        handle.write("素材位于 `sources/编号-原目录名`。打开 `RESTORED-MAP.json` 的 `sources` 查看原路径与新路径对应关系；工程入口和图片位于相应来源目录。\n\n")
        handle.write("不会写回旧电脑绝对路径，也不会自动重建 Codex 的旧会话侧边栏。\n\n")
        handle.write("旧电脑缺失来源：{}；读取错误：{}；排除记录：{}。\n".format(
            len(manifest["missing_paths"]), len(manifest["errors"]), len(manifest["excluded"])))
        if incomplete:
            handle.write("\n此包不完整，当前仅恢复可用部分。查看映射清单中的 `missing_paths` 和 `errors`，在旧电脑补齐后重新打包。\n")
    # Do not restore owners, setuid/setgid bits, ACLs or platform-specific metadata.
    # Apply ordinary modes only after all byte verification and report writes.
    for name, entry in sorted(entries.items(), key=lambda item: item[0].count("/"), reverse=True):
        if entry["type"] != "symlink":
            path = destination(output, name)
            member = members[name]
            os.utime(path, (member.mtime, member.mtime))
            if os.name != "nt":
                os.chmod(path, member.mode & 0o777)
    return incomplete


def remove_created_output(path):
    def repair(function, failed_path, _exc):
        os.chmod(failed_path, stat.S_IRWXU)
        function(failed_path)
    shutil.rmtree(path, onerror=repair)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-dir", type=Path, required=True, help="含 manifest.json 及全部分卷的目录")
    parser.add_argument("--output-dir", type=Path, required=True, help="必须尚不存在的新恢复目录")
    args = parser.parse_args()
    output = Path(os.path.abspath(os.path.expanduser(str(args.output_dir))))
    created = False
    try:
        if os.path.lexists(output):
            fail("输出目录已存在；请选择新目录，现有文件不会被覆盖: {}".format(output))
        if not output.parent.is_dir():
            fail("输出目录的父目录必须已存在: {}".format(output.parent))
        # Follow the user's chosen parent once, then reserve a fresh directory.
        output = output.parent.resolve() / output.name
        if os.path.lexists(output):
            fail("输出目录已存在: {}".format(output))
        bundle = args.bundle_dir.expanduser().resolve(strict=True)
        if not bundle.is_dir():
            fail("素材包路径不是目录")
        manifest = read_manifest(bundle)
        roots, entries = index_manifest(manifest)
        with tempfile.TemporaryDirectory(prefix="001-materials-check-") as temporary:
            archive_path = Path(temporary) / "verified.tar.gz"
            combine_parts(bundle, manifest, archive_path)
            members = check_archive(archive_path, entries)
            output.mkdir(mode=0o700, exist_ok=False)
            created = True
            incomplete = write_restoration(archive_path, output, roots, entries, members, manifest)
        file_count = sum(entry["type"] == "file" for entry in entries.values())
        print("已校验并恢复 {} 个文件: {}".format(file_count, output))
        print("来源映射: {}".format(output / "RESTORED-MAP.json"))
        if incomplete:
            print("素材包不完整：旧电脑缺失来源 {} 项、读取错误 {} 项。已恢复可用文件；需补齐后重新打包。".format(
                len(manifest["missing_paths"]), len(manifest["errors"])), file=sys.stderr)
            return 2
        return 0
    except (OSError, ValueError, OverflowError, EOFError, tarfile.TarError) as error:
        if created:
            try:
                remove_created_output(output)
            except OSError as cleanup_error:
                print("本次创建的目录清理失败: {} ({})".format(output, cleanup_error), file=sys.stderr)
        print("恢复失败: {}".format(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
