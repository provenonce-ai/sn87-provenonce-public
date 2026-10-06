"""Internal fail-closed filesystem controls for create-only evidence bundles."""

from __future__ import annotations

import os
import stat
from contextlib import suppress
from pathlib import Path


def stable_stat(metadata: os.stat_result) -> tuple[int, ...]:
    """Return the metadata fields used to detect a changed filesystem object."""

    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def fstat_descriptor(
    descriptor: int, label: str, *, error_type: type[ValueError]
) -> os.stat_result:
    """Read descriptor metadata without exposing a low-level filesystem failure."""

    try:
        return os.fstat(descriptor)
    except OSError as error:
        raise error_type(f"{label} metadata could not be read safely") from error


def close_descriptor(descriptor: int) -> None:
    """Best-effort close after the claim-bearing checks have completed."""

    with suppress(OSError):
        os.close(descriptor)


def directory_open_flags(*, error_type: type[ValueError]) -> int:
    """Return every control required by the directory-anchor contract."""

    no_follow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if type(no_follow) is not int or no_follow == 0 or type(directory) is not int or directory == 0:
        raise error_type(
            "descriptor-anchored evidence directories are unsupported on this platform"
        )
    return os.O_RDONLY | no_follow | directory


def file_safety_flags(*, error_type: type[ValueError]) -> int:
    """Return every control required to reject links and avoid FIFO blocking."""

    no_follow = getattr(os, "O_NOFOLLOW", None)
    non_blocking = getattr(os, "O_NONBLOCK", None)
    if (
        type(no_follow) is not int
        or no_follow == 0
        or type(non_blocking) is not int
        or non_blocking == 0
    ):
        raise error_type("descriptor-anchored evidence files are unsupported on this platform")
    return no_follow | non_blocking


def absolute_path(path: Path, *, error_type: type[ValueError], label: str) -> Path:
    """Normalize one caller path without allowing a raw path failure to escape."""

    try:
        return path.absolute()
    except (NotImplementedError, OSError, UnicodeError, ValueError) as error:
        raise error_type(f"{label} path is invalid") from error


def open_directory_path(
    path: Path,
    *,
    create_missing: bool,
    error_type: type[ValueError],
) -> tuple[int, Path]:
    """Open a directory path componentwise without following symbolic links."""

    flags = directory_open_flags(error_type=error_type)
    absolute = absolute_path(path, error_type=error_type, label="evidence directory")
    components = absolute.parts
    try:
        descriptor = os.open(components[0], flags)
    except (NotImplementedError, OSError, UnicodeError, ValueError) as error:
        raise error_type("evidence directory path could not be anchored safely") from error
    try:
        for component in components[1:]:
            try:
                next_descriptor = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError:
                if not create_missing:
                    raise error_type(
                        "evidence directory path could not be anchored safely"
                    ) from None
                try:
                    os.mkdir(component, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                except (NotImplementedError, OSError, UnicodeError, ValueError) as error:
                    raise error_type(
                        "evidence directory path could not be created safely"
                    ) from error
                try:
                    next_descriptor = os.open(component, flags, dir_fd=descriptor)
                except (NotImplementedError, OSError, UnicodeError, ValueError) as error:
                    raise error_type(
                        "evidence directory path could not be anchored safely"
                    ) from error
            except (NotImplementedError, OSError, UnicodeError, ValueError) as error:
                raise error_type("evidence directory path could not be anchored safely") from error
            close_descriptor(descriptor)
            descriptor = next_descriptor
        return descriptor, absolute
    except BaseException:
        close_descriptor(descriptor)
        raise


def open_new_bundle_directory(
    destination: Path, *, error_type: type[ValueError]
) -> tuple[int, Path]:
    """Create a final bundle directory atomically below an anchored parent."""

    absolute = absolute_path(destination, error_type=error_type, label="evidence destination")
    parent_descriptor, _absolute_parent = open_directory_path(
        absolute.parent,
        create_missing=True,
        error_type=error_type,
    )
    try:
        try:
            os.mkdir(absolute.name, mode=0o700, dir_fd=parent_descriptor)
        except FileExistsError as error:
            raise FileExistsError(f"evidence destination already exists: {destination}") from error
        except (NotImplementedError, OSError, UnicodeError, ValueError) as error:
            raise error_type("evidence bundle destination could not be created safely") from error
        try:
            return (
                os.open(
                    absolute.name,
                    directory_open_flags(error_type=error_type),
                    dir_fd=parent_descriptor,
                ),
                absolute,
            )
        except (NotImplementedError, OSError, UnicodeError, ValueError) as error:
            raise error_type("evidence bundle destination could not be opened safely") from error
    finally:
        close_descriptor(parent_descriptor)


def open_regular_file_at(
    directory_descriptor: int,
    name: str,
    max_bytes: int,
    *,
    error_type: type[ValueError],
    label_prefix: str,
) -> int:
    """Open and validate one bounded regular entry below an anchored directory."""

    flags = os.O_RDONLY | file_safety_flags(error_type=error_type)
    try:
        descriptor = os.open(name, flags, dir_fd=directory_descriptor)
    except (NotImplementedError, OSError, UnicodeError, ValueError) as error:
        raise error_type(f"{label_prefix} could not be opened safely: {name}") from error
    try:
        metadata = fstat_descriptor(
            descriptor,
            f"{label_prefix} {name}",
            error_type=error_type,
        )
        if not stat.S_ISREG(metadata.st_mode):
            raise error_type(f"{label_prefix} must be a regular file: {name}")
        if metadata.st_nlink != 1:
            raise error_type(f"{label_prefix} must have exactly one link: {name}")
        if metadata.st_size > max_bytes:
            raise error_type(f"{label_prefix} exceeds its byte limit: {name}")
        return descriptor
    except BaseException:
        close_descriptor(descriptor)
        raise


def read_open_file(
    descriptor: int,
    name: str,
    max_bytes: int,
    *,
    error_type: type[ValueError],
    label_prefix: str,
    limit_message: str | None = None,
) -> bytes:
    """Read one bounded snapshot from an already-open regular file."""

    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > max_bytes or os.read(descriptor, 1):
            raise error_type(limit_message or f"{label_prefix} exceeds its byte limit: {name}")
        return payload
    except error_type:
        raise
    except (OSError, UnicodeError, ValueError) as error:
        raise error_type(f"{label_prefix} could not be read safely: {name}") from error


def write_new_bundle_file(
    directory_descriptor: int,
    name: str,
    payload: bytes,
    *,
    error_type: type[ValueError],
    label_prefix: str,
) -> None:
    """Create one regular entry exclusively below an anchored directory."""

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | file_safety_flags(error_type=error_type)
    try:
        descriptor = os.open(name, flags, 0o600, dir_fd=directory_descriptor)
    except (NotImplementedError, OSError, UnicodeError, ValueError) as error:
        raise error_type(f"{label_prefix} could not be created exclusively: {name}") from error
    try:
        metadata = fstat_descriptor(
            descriptor,
            f"{label_prefix} {name}",
            error_type=error_type,
        )
        if not stat.S_ISREG(metadata.st_mode):
            raise error_type(f"{label_prefix} must be a regular file: {name}")
        remaining = memoryview(payload)
        while remaining:
            written = os.write(descriptor, remaining)
            if written < 1:
                raise error_type(f"{label_prefix} write did not progress: {name}")
            remaining = remaining[written:]
        os.fsync(descriptor)
    except error_type:
        raise
    except (OSError, ValueError) as error:
        raise error_type(f"{label_prefix} could not be written safely: {name}") from error
    finally:
        close_descriptor(descriptor)


def directory_descriptor_matches_path(directory_descriptor: int, path: Path) -> bool:
    """Return whether a path still names the exact anchored directory snapshot."""

    try:
        descriptor_stat = os.fstat(directory_descriptor)
        path_stat = os.stat(path, follow_symlinks=False)
    except (OSError, UnicodeError, ValueError):
        return False
    return (
        stat.S_ISDIR(path_stat.st_mode)
        and descriptor_stat.st_dev == path_stat.st_dev
        and descriptor_stat.st_ino == path_stat.st_ino
    )


def read_bounded_regular_file(
    path: Path,
    max_bytes: int,
    *,
    label: str,
    error_type: type[ValueError],
) -> bytes:
    """Read one exact bounded file snapshot without following the final path entry."""

    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")
    try:
        if path.is_symlink():
            raise error_type(f"{label} must be a regular file")
    except error_type:
        raise
    except (OSError, UnicodeError, ValueError) as error:
        raise error_type(f"{label} path is invalid") from error
    flags = os.O_RDONLY | file_safety_flags(error_type=error_type)
    try:
        descriptor = os.open(path, flags)
    except (NotImplementedError, OSError, UnicodeError, ValueError) as error:
        raise error_type(f"{label} could not be opened safely") from error
    try:
        metadata = fstat_descriptor(descriptor, label, error_type=error_type)
        if not stat.S_ISREG(metadata.st_mode):
            raise error_type(f"{label} must be a regular file")
        if metadata.st_size > max_bytes:
            raise error_type(f"{label} exceeds the {max_bytes}-byte limit")
        return read_open_file(
            descriptor,
            label,
            max_bytes,
            error_type=error_type,
            label_prefix=label,
            limit_message=f"{label} exceeds the {max_bytes}-byte limit",
        )
    finally:
        close_descriptor(descriptor)
