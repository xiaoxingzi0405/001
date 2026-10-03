#!/usr/bin/env python3
"""Package old-machine material and push a resumable backup branch using Git."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path


MIB = 1024 * 1024
DEFAULT_REMOTE = "https://github.com/xiaoxingzi0405/001.git"
STATE_NAME = "_upload-state.json"
METADATA_RESERVE = 64 * 1024
ATTRIBUTES = "* -text -filter -ident -working-tree-encoding\n"


class UploadError(Exception):
    pass


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(MIB), b""):
            result.update(chunk)
    return result.hexdigest()


def atomic_json(path, value):
    temporary = path.with_name(path.name + ".new")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(str(temporary), str(path))


def git(repository, arguments, operation, check=True):
    # Existing credential helpers and platform authentication remain in effect.
    # Capture diagnostics, but do not print them: helpers can include sensitive URLs.
    environment = os.environ.copy()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    command = ["git"]
    if repository is not None:
        command += ["-C", str(repository)]
    command += arguments
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                encoding="utf-8", errors="replace", env=environment)
    except OSError as error:
        raise UploadError("Git is unavailable; install Git on this machine first.") from error
    if check and result.returncode:
        diagnostic = (result.stdout + result.stderr).lower()
        reason = "Git returned exit code {}".format(result.returncode)
        if any(value in diagnostic for value in ("authentication failed", "could not read username",
                                                 "permission denied", "terminal prompts disabled")):
            reason = "existing Git authentication is missing or does not permit this operation"
        elif "non-fast-forward" in diagnostic or "fetch first" in diagnostic:
            reason = "the remote branch advanced; no history was overwritten"
        elif "could not resolve host" in diagnostic or "failed to connect" in diagnostic:
            reason = "the remote could not be reached"
        elif "repository not found" in diagnostic:
            reason = "the repository could not be read with the existing Git authentication"
        raise UploadError("{} failed: {}. Raw Git diagnostics were withheld to protect credentials."
                          .format(operation, reason))
    return result.stdout.strip(), result.returncode


def validate_remote(value):
    if value == DEFAULT_REMOTE:
        return value
    # A local bare repository is supported for offline tests. Other hosted targets,
    # URL credentials, and replacement authentication are intentionally unsupported.
    if "://" in value or value.startswith("git@"):
        raise UploadError("--remote accepts the default GitHub target or a local bare Git repository.")
    candidate = Path(value).expanduser().resolve()
    if not candidate.is_dir():
        raise UploadError("The local test remote does not exist.")
    output, _ = git(candidate, ["rev-parse", "--is-bare-repository"], "Validate local test remote")
    if output != "true":
        raise UploadError("The local test remote must be a bare Git repository.")
    return str(candidate)


def inspect_package(directory):
    manifest_path = directory / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise UploadError("The package manifest is missing or is a symbolic link.")
    if manifest_path.stat().st_size >= 90 * MIB:
        raise UploadError("manifest.json is at least 90 MiB; upload is stopped before committing it.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise UploadError("The package manifest could not be read.") from error
    files = [{"name": "manifest.json", "size_bytes": manifest_path.stat().st_size,
              "sha256": digest(manifest_path)}]
    archive = manifest.get("archive", {})
    if archive.get("valid"):
        combined = hashlib.sha256()
        total_size = 0
        seen = set()
        for index, record in enumerate(archive.get("parts", []), 1):
            name = record.get("name", "")
            if name != "local-materials.tar.gz.part{:04d}".format(index) or name in seen:
                raise UploadError("The package contains an invalid or repeated part name.")
            seen.add(name)
            path = directory / name
            if path.is_symlink() or not path.is_file():
                raise UploadError("An archive part is missing or is a symbolic link: {}".format(name))
            size = path.stat().st_size
            if size > 24 * MIB or size != record.get("size_bytes"):
                raise UploadError("An archive part has an invalid size: {}".format(name))
            part_hash = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(MIB), b""):
                    part_hash.update(chunk)
                    combined.update(chunk)
            if part_hash.hexdigest() != record.get("sha256"):
                raise UploadError("An archive part failed SHA256 verification: {}".format(name))
            total_size += size
            files.append(dict(record))
        if not seen or total_size != archive.get("size_bytes") or combined.hexdigest() != archive.get("sha256"):
            raise UploadError("The complete archive failed SHA256 or size verification.")
    return manifest, files


def make_batches(files, limit):
    batches = []
    current = []
    current_size = METADATA_RESERVE
    for record in files:
        if record["size_bytes"] + METADATA_RESERVE >= limit:
            raise UploadError("The batch limit is too small for {} plus upload metadata."
                              .format(record["name"]))
        if current and current_size + record["size_bytes"] >= limit:
            batches.append(current)
            current = []
            current_size = METADATA_RESERVE
        current.append(record["name"])
        current_size += record["size_bytes"]
    if current:
        batches.append(current)
    return batches


def branch_url(state):
    if state["remote"] == DEFAULT_REMOTE:
        return "https://github.com/xiaoxingzi0405/001/tree/" + state["branch"]
    return "Local test remote; branch: " + state["branch"]


def save_state(directory, state):
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    atomic_json(directory / STATE_NAME, state)


def initialize_clone(directory, state):
    repository = directory / "repository"
    if not repository.exists():
        partial = directory / "repository.partial"
        if partial.exists():
            partial.rename(directory / ("repository.failed-" + uuid.uuid4().hex[:8]))
        git(None, ["clone", "--depth", "1", "--single-branch", "--branch", state["base_branch"],
                   "--", state["remote"], str(partial)], "Clone repository")
        partial.rename(repository)
    remote, _ = git(repository, ["remote", "get-url", "origin"], "Check clone origin")
    if remote != state["remote"]:
        raise UploadError("The saved clone origin changed; upload was stopped.")
    branch, _ = git(repository, ["symbolic-ref", "--short", "HEAD"], "Check clone branch")
    if branch == state["base_branch"] and not state.get("initialized"):
        git(repository, ["checkout", "-b", state["branch"]], "Create isolated backup branch")
    elif branch != state["branch"]:
        raise UploadError("The saved clone is on an unexpected branch; upload was stopped.")
    if not state.get("initialized"):
        target = repository / "backups" / state["backup_id"]
        if target.exists():
            raise UploadError("The backup destination already exists; no files were overwritten.")
        remote_heads, _ = git(repository, ["ls-remote", "--heads", "origin", "refs/heads/" + state["branch"]],
                              "Check new backup branch")
        if remote_heads:
            raise UploadError("The new branch name already exists; no remote history was overwritten.")
        state["initialized"] = True
        state["last_local_commit"], _ = git(repository, ["rev-parse", "HEAD"], "Read base commit")
        save_state(directory, state)
    return repository


def copy_verified(source, destination, record):
    if source.is_symlink() or digest(source) != record["sha256"]:
        raise UploadError("A local package file changed: {}".format(record["name"]))
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".copying")
    shutil.copyfile(str(source), str(temporary))
    if temporary.stat().st_size != record["size_bytes"] or digest(temporary) != record["sha256"]:
        raise UploadError("A copied package file failed verification: {}".format(record["name"]))
    os.replace(str(temporary), str(destination))


def upload(directory, state, manifest, files):
    repository = initialize_clone(directory, state)
    records = {record["name"]: record for record in files}
    target = repository / "backups" / state["backup_id"]
    batches = state["batches"]
    for index in range(state["next_batch"], len(batches)):
        if state.get("pending_batch") is None:
            head, _ = git(repository, ["rev-parse", "HEAD"], "Read current commit")
            if head != state["last_local_commit"]:
                raise UploadError("The saved clone history changed; upload was stopped.")
            state.update(pending_batch=index, before_commit=head, pending_commit=None, status="transferring")
            save_state(directory, state)
        if state["pending_batch"] != index:
            raise UploadError("The saved batch state is inconsistent.")
        message = "Archive local materials {} batch {}/{}".format(state["backup_id"], index + 1, len(batches))
        if state.get("pending_commit") is None:
            head, _ = git(repository, ["rev-parse", "HEAD"], "Recover batch commit")
            if head != state["before_commit"]:
                parent, _ = git(repository, ["rev-parse", "HEAD^"], "Check recovered commit parent")
                subject, _ = git(repository, ["log", "-1", "--format=%s"], "Check recovered commit message")
                if parent != state["before_commit"] or subject != message:
                    raise UploadError("The pending local commit cannot be safely recovered.")
                state["pending_commit"] = head
            else:
                for name in batches[index]:
                    copy_verified(directory / name, target / name, records[name])
                attributes = target / ".gitattributes"
                attributes.write_text(ATTRIBUTES, encoding="utf-8")
                uploaded = [name for batch in batches[:index + 1] for name in batch]
                info = {"schema_version": 1, "backup_id": state["backup_id"], "branch": state["branch"],
                        "status": "transfer_finished" if index + 1 == len(batches) else "transferring",
                        "uploaded_package_files": uploaded, "expected_package_files": list(records),
                        "completed_batches": index + 1, "total_batches": len(batches),
                        "source_counts": manifest.get("counts", {}),
                        "scope": "Only readable local sources in manifest.json; inspect missing_paths, excluded and errors."}
                atomic_json(target / "upload-info.json", info)
                metadata_size = attributes.stat().st_size + (target / "upload-info.json").stat().st_size
                batch_size = sum(records[name]["size_bytes"] for name in batches[index]) + metadata_size
                if metadata_size >= 90 * MIB or batch_size >= state["batch_limit_bytes"] or batch_size >= 128 * MIB:
                    raise UploadError("The actual batch and metadata exceed the safe size limit; no commit was made.")
                relative = str(target.relative_to(repository))
                names = [relative + "/" + name for name in batches[index]]
                names += [relative + "/.gitattributes", relative + "/upload-info.json"]
                # Force exact package bytes, regardless of parent .gitattributes or ignore rules.
                git(repository, ["add", "-f", "--"] + names, "Stage backup batch")
                staged, _ = git(repository, ["diff", "--cached", "--name-only", "-z"], "Check staged paths")
                if not set(staged.split("\0")) - {""} <= set(names):
                    raise UploadError("Unexpected staged files were found; no commit was made.")
                for name in batches[index]:
                    blob, _ = git(repository, ["rev-parse", ":" + relative + "/" + name], "Check staged package blob")
                    expected, _ = git(repository, ["hash-object", "--no-filters", str(target / name)], "Hash package blob")
                    if blob != expected:
                        raise UploadError("Git transformed a package file; no commit was made.")
                git(repository, ["-c", "user.name=Local Material Backup", "-c",
                                 "user.email=local-material-backup@users.noreply.github.com",
                                 "commit", "-m", message], "Commit backup batch")
                state["pending_commit"], _ = git(repository, ["rev-parse", "HEAD"], "Read batch commit")
            save_state(directory, state)
        print("Pushing batch {}/{} (each batch below 128 MiB)...".format(index + 1, len(batches)), flush=True)
        git(repository, ["push", "origin", "HEAD:refs/heads/" + state["branch"]], "Push backup batch")
        remote_heads, _ = git(repository, ["ls-remote", "--heads", "origin", "refs/heads/" + state["branch"]],
                              "Verify pushed backup commit")
        remote_commit = remote_heads.split()[0] if remote_heads else ""
        if remote_commit != state["pending_commit"]:
            raise UploadError("The remote commit differs from the uploaded batch; local state was retained.")
        state.update(next_batch=index + 1, last_local_commit=state["pending_commit"],
                     last_uploaded_commit=state["pending_commit"], pending_commit=None, pending_batch=None)
        save_state(directory, state)
    state["status"] = "transfer_finished"
    save_state(directory, state)


def report(manifest, state):
    counts = manifest.get("counts", {})
    print("Repository branch: {}".format(branch_url(state)))
    print("Backup path: backups/{}/".format(state["backup_id"]))
    uploaded_count = counts.get("file_count", 0) if manifest.get("archive", {}).get("valid") else 0
    print("Uploaded readable files: {}. Missing paths: {}. Excluded paths: {}. Read errors: {}."
          .format(uploaded_count, len(manifest.get("missing_paths", [])),
                  len(manifest.get("excluded", [])), len(manifest.get("errors", []))))
    print("Inspect manifest.json for exact missing paths and credential exclusions. This is not a claim that all historical material exists.")
    if not manifest.get("archive", {}).get("valid"):
        print("Only the source report was uploaded; no valid material archive was available.")
    return 2 if (manifest.get("missing_paths") or manifest.get("errors") or
                 not manifest.get("archive", {}).get("valid") or not counts.get("file_count")) else 0


def main():
    repository = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paths-file", type=Path, default=repository / "conversation-archive" / "local-sources.json")
    parser.add_argument("--project-dir", help="Additional actual local source directory.")
    parser.add_argument("--work-dir", type=Path, help="New output/state directory; never an existing checkout.")
    parser.add_argument("--resume", type=Path, help="Resume from the printed _upload-state.json or its directory.")
    parser.add_argument("--remote", default=DEFAULT_REMOTE, help="Default GitHub target, or a local bare test remote.")
    parser.add_argument("--base-branch", default="main")
    parser.add_argument("--part-size-mib", type=int, default=24, choices=range(1, 25), metavar="1..24")
    parser.add_argument("--batch-size-mib", type=int, default=120, choices=range(1, 128), metavar="1..127")
    args = parser.parse_args()
    directory = None
    state = None
    try:
        if args.resume:
            directory = args.resume.expanduser().resolve()
            if directory.name == STATE_NAME:
                directory = directory.parent
            state = json.loads((directory / STATE_NAME).read_text(encoding="utf-8"))
            if state.get("schema_version") != 1 or not re.fullmatch(r"[A-Za-z0-9_-]+", state.get("backup_id", "")):
                raise UploadError("The saved upload state is invalid.")
            state["remote"] = validate_remote(state["remote"])
            if state["branch"] != "archive/local-materials-" + state["backup_id"]:
                raise UploadError("The saved backup branch is invalid.")
        else:
            remote = validate_remote(args.remote)
            git(None, ["check-ref-format", "--branch", args.base_branch], "Validate base branch")
            identifier = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:12]
            directory = (args.work_dir.expanduser().resolve() if args.work_dir else
                         Path(tempfile.gettempdir()).resolve() / ("001-local-upload-" + identifier))
            if directory.exists():
                raise UploadError("Use a new --work-dir or --resume; existing local data is never overwritten.")
            print("Packaging local files on this machine. Cloud-only machines cannot access old Mac paths.", flush=True)
            command = [sys.executable, str(repository / "tools" / "pack-local-materials.py"),
                       "--paths-file", str(args.paths_file.expanduser().resolve()),
                       "--output-dir", str(directory), "--part-size-mib", str(args.part_size_mib)]
            if args.project_dir:
                command += ["--project-dir", args.project_dir]
            # The entire working directory is the packer's excluded output directory.
            # Clone/state files are created only after packaging, avoiding self-inclusion.
            result = subprocess.run(command)
            if result.returncode not in (0, 2) or not (directory / "manifest.json").is_file():
                raise UploadError("Packaging failed before producing a manifest; no upload was attempted.")
            manifest, files = inspect_package(directory)
            state = {"schema_version": 1, "backup_id": identifier, "remote": remote,
                     "branch": "archive/local-materials-" + identifier, "base_branch": args.base_branch,
                     "created_at": datetime.now(timezone.utc).isoformat(), "status": "ready_to_clone",
                     "files": files, "batch_limit_bytes": args.batch_size_mib * MIB,
                     "batches": make_batches(files, args.batch_size_mib * MIB), "next_batch": 0,
                     "pending_batch": None, "pending_commit": None, "initialized": False}
            save_state(directory, state)
        print("Resume state: {}".format(directory / STATE_NAME), flush=True)
        manifest, files = inspect_package(directory)
        if files != state["files"] or make_batches(files, state["batch_limit_bytes"]) != state["batches"]:
            raise UploadError("The saved package or batch plan changed; upload was stopped.")
        if state["status"] != "transfer_finished":
            upload(directory, state, manifest, files)
        return report(manifest, state)
    except (UploadError, OSError, ValueError, KeyError) as error:
        if directory is not None and state is not None:
            state["last_error"] = str(error)
            try:
                save_state(directory, state)
            except OSError:
                pass
            print("Saved state: {}".format(directory / STATE_NAME), file=sys.stderr)
            print("Uploaded branch (may be partial): {}".format(branch_url(state)), file=sys.stderr)
            print("Resume using: python3 tools/upload-local-materials.py --resume <saved-state-path>", file=sys.stderr)
        print("Upload stopped: {}".format(error), file=sys.stderr)
        print("Source files and existing checkouts were retained. If authentication failed, use your existing secure Git credential setup; do not paste tokens into chat.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
