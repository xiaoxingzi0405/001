#!/usr/bin/env python3
"""Package locally accessible source material without third-party dependencies."""

import argparse
import gzip
import hashlib
import json
import os
import stat
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path


MIB = 1024 * 1024
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


def within(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def exclusion_reason(path):
    """Only metadata and explicitly named credential configuration are ignored."""
    names = tuple(component.lower() for component in path.parts)
    name = path.name.lower()
    if ".git" in names:
        return "git_metadata"
    if name == ".env" or (name.startswith(".env.") and not name.endswith(TEMPLATE_SUFFIXES)):
        return "environment_secret_configuration"
    if name in CREDENTIAL_NAMES:
        return "credential_configuration"
    if len(names) >= 2:
        if names[-2:] in ((".aws", "credentials"), (".docker", "config.json")):
            return "credential_configuration"
        if names[-2] == ".ssh" and name.startswith("id_") and not name.endswith(".pub"):
            return "private_ssh_key"
        if names[-2:] == ("gcloud", "application_default_credentials.json"):
            return "credential_configuration"
    return None


class SplitWriter:
    """Stream one gzip archive into numbered, independently hashed chunks."""

    def __init__(self, directory, limit):
        self.directory = directory
        self.limit = limit
        self.handle = None
        self.part_size = 0
        self.part_hash = None
        self.parts = []
        self.total_size = 0
        self.total_hash = hashlib.sha256()

    def _finish_part(self):
        if self.handle is not None:
            self.handle.close()
            self.parts.append({
                "name": Path(self.handle.name).name,
                "size_bytes": self.part_size,
                "sha256": self.part_hash.hexdigest(),
            })
            self.handle = None

    def write(self, data):
        view = memoryview(data)
        count = len(view)
        while view:
            if self.handle is None:
                name = "local-materials.tar.gz.part{:04d}".format(len(self.parts) + 1)
                self.handle = (self.directory / name).open("xb")
                self.part_size = 0
                self.part_hash = hashlib.sha256()
            chunk = view[:self.limit - self.part_size]
            self.handle.write(chunk)
            self.part_hash.update(chunk)
            self.total_hash.update(chunk)
            self.part_size += len(chunk)
            self.total_size += len(chunk)
            view = view[len(chunk):]
            if self.part_size == self.limit:
                self._finish_part()
        return count

    def flush(self):
        if self.handle is not None:
            self.handle.flush()

    def close(self):
        self._finish_part()


class HashReader:
    def __init__(self, handle):
        self.handle = handle
        self.hash = hashlib.sha256()
        self.count = 0

    def read(self, size=-1):
        data = self.handle.read(size)
        self.hash.update(data)
        self.count += len(data)
        return data


def load_requests(paths_file, project_dir):
    with paths_file.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    if not isinstance(config, dict):
        raise ValueError("The paths file must contain a JSON object.")
    requests = []
    for field in ("source_roots", "source_files"):
        values = config.get(field, [])
        if not isinstance(values, list) or any(not isinstance(value, str) or not value for value in values):
            raise ValueError("{} must be an array of nonempty path strings.".format(field))
        requests.extend({"requested_path": value, "source_list": field} for value in values)
    if project_dir is not None:
        requests.insert(0, {"requested_path": os.path.abspath(os.path.expanduser(project_dir)),
                            "source_list": "--project-dir"})
    return requests


def collect_sources(requests, output_dir, manifest):
    candidates = []
    for index, request in enumerate(requests, 1):
        record = dict(request, source_id="{:04d}".format(index))
        manifest["requested_sources"].append(record)
        expanded = Path(os.path.expanduser(request["requested_path"]))
        if not expanded.is_absolute():
            record["status"] = "excluded"
            manifest["excluded"].append(dict(record, reason="input_path_is_not_absolute"))
            continue
        path = Path(os.path.abspath(str(expanded)))
        record["resolved_path"] = str(path)
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            record["status"] = "missing"
            manifest["missing_paths"].append(dict(record))
            continue
        except OSError as error:
            record["status"] = "unreadable"
            manifest["errors"].append(dict(record, error=str(error)))
            continue
        reason = exclusion_reason(path)
        if stat.S_ISLNK(metadata.st_mode):
            reason = "requested_source_is_a_symbolic_link"
        elif within(path, output_dir):
            reason = "transfer_output"
        elif not (stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)):
            reason = "unsupported_special_file"
        if reason:
            record["status"] = "excluded"
            manifest["excluded"].append(dict(record, reason=reason))
            continue
        candidates.append((path, metadata, record))

    # Handle parent directories before nested sources, so the same data is not duplicated.
    candidates.sort(key=lambda item: (not stat.S_ISDIR(item[1].st_mode), len(item[0].parts), item[2]["source_id"]))
    selected = []
    for path, metadata, record in candidates:
        covered = next((other for root, _, other in selected
                        if path == root or (other["kind"] == "directory" and within(path, root))), None)
        if covered:
            record.update(status="covered_by_source", covered_by_source=covered["source_id"])
            continue
        record.update(status="available", kind="directory" if stat.S_ISDIR(metadata.st_mode) else "file",
                      archive_path="sources/{}-{}".format(record["source_id"], path.name or "root"))
        selected.append((path, metadata, record))
    return selected


def package_sources(sources, output_dir, manifest, part_limit):
    writer = SplitWriter(output_dir, part_limit)

    def excluded(path, archive_path, reason):
        manifest["excluded"].append({"source_path": str(path), "archive_path": archive_path, "reason": reason})

    def visit(archive, path, archive_path, root):
        if within(path, output_dir):
            excluded(path, archive_path, "transfer_output")
            return
        reason = exclusion_reason(path)
        if reason:
            excluded(path, archive_path, reason)
            return
        copying_file = False
        try:
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                original_target = os.readlink(path)
                target = path.resolve(strict=False)
                if not within(target, root.resolve()):
                    excluded(path, archive_path, "symbolic_link_escapes_source_root")
                    return
                if within(target, output_dir.resolve()):
                    excluded(path, archive_path, "symbolic_link_targets_transfer_output")
                    return
                if exclusion_reason(target):
                    excluded(path, archive_path, "symbolic_link_targets_excluded_configuration")
                    return
                info = archive.gettarinfo(str(path), arcname=archive_path)
                # Resolving the target also handles links that leave and reenter the source root.
                # Original link text is retained in the manifest; archive links stay inside their root.
                info.linkname = os.path.relpath(target, path.parent.resolve())
                archive.addfile(info)
                manifest["entries"].append({"source_path": str(path), "archive_path": archive_path,
                                            "type": "symlink", "original_target": original_target,
                                            "archive_target": info.linkname})
                return
            if stat.S_ISDIR(metadata.st_mode):
                archive.addfile(archive.gettarinfo(str(path), arcname=archive_path))
                manifest["entries"].append({"source_path": str(path), "archive_path": archive_path, "type": "directory"})
                with os.scandir(path) as iterator:
                    children = sorted(iterator, key=lambda child: child.name)
                for child in children:
                    visit(archive, path / child.name, archive_path + "/" + child.name, root)
                return
            if not stat.S_ISREG(metadata.st_mode):
                excluded(path, archive_path, "unsupported_special_file")
                return
            # Inspect only a key header; no credential content is written to the manifest or stdout.
            with path.open("rb") as handle:
                prefix = handle.read(256)
                if any(header in prefix for header in PRIVATE_KEY_HEADERS):
                    excluded(path, archive_path, "private_key_content")
                    return
                handle.seek(0)
                opened = os.fstat(handle.fileno())
                if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
                    raise OSError("The source changed while being opened.")
                info = archive.gettarinfo(str(path), arcname=archive_path)
                # Each requested file has its own bytes and hash, even if the filesystem uses hard links.
                info.type = tarfile.REGTYPE
                info.linkname = ""
                info.size = opened.st_size
                reader = HashReader(handle)
                copying_file = True
                archive.addfile(info, reader)
                after = os.fstat(handle.fileno())
                current = path.lstat()
                if (opened.st_size, opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or (
                    opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns
                ) != (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns):
                    raise RuntimeError("The source changed during archiving: {}".format(path))
                manifest["entries"].append({"source_path": str(path), "archive_path": archive_path,
                                            "type": "file", "size_bytes": reader.count,
                                            "sha256": reader.hash.hexdigest()})
                copying_file = False
        except OSError as error:
            # Open/scan failures leave an explicit report. A read failure mid-member aborts instead.
            if not copying_file and isinstance(error, (PermissionError, FileNotFoundError)):
                manifest["errors"].append({"source_path": str(path), "archive_path": archive_path, "error": str(error)})
            else:
                raise

    try:
        with gzip.GzipFile(filename="", mode="wb", fileobj=writer, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT, dereference=False) as archive:
                for path, metadata, record in sources:
                    root = path if stat.S_ISDIR(metadata.st_mode) else path.parent
                    visit(archive, path, record["archive_path"], root)
    finally:
        writer.close()
        manifest["archive"] = {"format": "tar.gz", "valid": False,
                               "concatenate_parts_in_listed_order": True,
                               "size_bytes": writer.total_size, "sha256": writer.total_hash.hexdigest(),
                               "part_limit_bytes": part_limit, "parts": writer.parts}
    manifest["archive"]["valid"] = True


def main():
    repository = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", help="Additional local project directory (does not replace JSON sources).")
    parser.add_argument("--paths-file", type=Path, default=repository / "conversation-archive" / "local-sources.json")
    parser.add_argument("--output-dir", type=Path,
                        default=Path.cwd() / ("local-materials-transfer-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")))
    parser.add_argument("--part-size-mib", type=int, default=24, choices=range(1, 25), metavar="1..24")
    args = parser.parse_args()
    try:
        requests = load_requests(args.paths_file, args.project_dir)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    output_dir = Path(os.path.abspath(os.path.expanduser(str(args.output_dir))))
    try:
        output_dir.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        parser.error("Use a new output directory; existing data is never overwritten: {}".format(error))
    manifest = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
                "status": "not_packed", "paths_file": str(args.paths_file.resolve()),
                "requested_sources": [], "missing_paths": [], "excluded": [], "errors": [], "entries": []}
    exit_code = 0
    try:
        sources = collect_sources(requests, output_dir, manifest)
        if not sources:
            manifest["status"] = "no_accessible_sources"
            exit_code = 2
        else:
            package_sources(sources, output_dir, manifest, args.part_size_mib * MIB)
            manifest["status"] = "packed_available_sources"
            if manifest["errors"]:
                exit_code = 2
    except Exception as error:
        manifest["status"] = "failed"
        manifest["errors"].append({"error": str(error), "type": type(error).__name__})
        exit_code = 2
    files = [entry for entry in manifest["entries"] if entry["type"] == "file"]
    manifest["counts"] = {"file_count": len(files), "file_bytes": sum(entry["size_bytes"] for entry in files),
                          "directory_count": sum(entry["type"] == "directory" for entry in manifest["entries"]),
                          "symlink_count": sum(entry["type"] == "symlink" for entry in manifest["entries"]),
                          "missing_path_count": len(manifest["missing_paths"]),
                          "excluded_path_count": len(manifest["excluded"]), "error_count": len(manifest["errors"])}
    with (output_dir / "manifest.json").open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print("Status: {}. Files: {}. File bytes: {}. Missing paths: {}. Excluded paths: {}. Errors: {}.".format(
        manifest["status"], len(files), manifest["counts"]["file_bytes"], len(manifest["missing_paths"]),
        len(manifest["excluded"]), len(manifest["errors"])))
    print("Manifest: {}".format(output_dir / "manifest.json"))
    print("This command only packages accessible local files; it does not upload them.")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
