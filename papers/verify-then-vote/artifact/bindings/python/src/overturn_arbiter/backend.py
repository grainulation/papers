"""Reducer backends.

The public API talks to a ``Backend``. Today the only implementation runs
the Rust ``overturn`` binary (``--reduce [--emit-artifact]``, ``--assign-ids``,
``--replay-from --json``, ``--print-policy``, ``--version``). A PyO3
extension can replace it later by implementing the same methods on
in-memory dicts.
"""
from __future__ import annotations

import abc
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

from .types import VerifyResult

_EXE = "overturn.exe" if sys.platform == "win32" else "overturn"
_BUNDLED = Path(__file__).resolve().parent / "_bin" / _EXE


class OverturnError(RuntimeError):
    """The reducer rejected its input or could not run."""

    def __init__(self, message: str, exit_code: Optional[int] = None, stderr: str = ""):
        super().__init__(message)
        self.exit_code = exit_code
        self.stderr = stderr


class Backend(abc.ABC):
    """What the API needs from a reducer. All payloads are JSON-shaped dicts
    in the Rust wire format (see ``run_reduce`` in ``overturn/src/main.rs``)."""

    @abc.abstractmethod
    def reduce(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """A ``--reduce`` input object -> ``ReductionOutput`` (+ ``p3_rejected``)."""

    @abc.abstractmethod
    def assign_ids(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """A ``--reduce`` input object -> the same object with content ids."""

    @abc.abstractmethod
    def seal(self, request: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """A ``--reduce`` input object -> (``ReductionOutput`` + ``p3_rejected``,
        the ``bran-artifact/{2,3,4}`` file sealing it; ``--emit-artifact``)."""

    @abc.abstractmethod
    def default_policy(self) -> Dict[str, Any]:
        """The full serialized default policy (``OverturnCompiler``)."""

    @abc.abstractmethod
    def replay(self, artifact: Dict[str, Any]) -> VerifyResult:
        """Verify hashes of an artifact file, re-reduce, compare outputs."""

    def print_policy(self, overlay: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """``{policy, policy_hash, canonical_policy_json, reducer_constants_id, preset}``
        for the default policy plus ``overlay`` (``--print-policy``)."""
        raise NotImplementedError

    def version(self) -> Dict[str, Any]:
        """Reducer version, artifact formats, reducer-constants id (``--version``)."""
        raise NotImplementedError


def find_binary() -> str:
    """``OVERTURN_BIN`` if set, else the binary bundled in the wheel, else
    ``overturn`` on ``PATH``."""
    env = os.environ.get("OVERTURN_BIN")
    if env:
        if not Path(env).is_file():
            raise OverturnError(f"OVERTURN_BIN={env!r} is not a file")
        return env
    if _BUNDLED.is_file():
        if not os.access(_BUNDLED, os.X_OK):
            try:
                _BUNDLED.chmod(_BUNDLED.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            except OSError:
                pass
        return str(_BUNDLED)
    found = shutil.which("overturn")
    if found:
        return found
    raise OverturnError("no overturn binary: install a platform wheel, set OVERTURN_BIN, or put `overturn` on PATH")


class SubprocessBackend(Backend):
    """Runs the ``overturn`` binary once per call through temporary files."""

    def __init__(self, binary: Optional[str] = None, timeout: float = 120.0):
        self.binary = binary or find_binary()
        self.timeout = timeout
        self._default_policy: Optional[Dict[str, Any]] = None

    def __repr__(self) -> str:
        return f"SubprocessBackend({self.binary!r})"

    def _run(self, *args: str) -> "subprocess.CompletedProcess[str]":
        try:
            return subprocess.run([self.binary, "--no-color", *args], capture_output=True,
                                  text=True, timeout=self.timeout)
        except OSError as e:
            raise OverturnError(f"cannot run {self.binary}: {e}") from e

    def _with_input(self, flag: str, payload: Any, extra: Sequence[str] = (),
                    out_name: Optional[str] = None) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        """Run ``overturn FLAG <payload file> *extra``; ``out_name`` names a file
        the run writes (passed as the last argument), read back as JSON."""
        with tempfile.TemporaryDirectory(prefix="overturn-") as d:
            p = Path(d) / "in.json"
            p.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            out = Path(d) / out_name if out_name else None
            r = self._run(flag, str(p), *extra, *([str(out)] if out else []))
            if r.returncode != 0:
                msg = r.stderr.strip().replace(str(p), "<input>")
                raise OverturnError(f"overturn {flag} failed (exit {r.returncode}): {msg}", r.returncode, r.stderr)
            written = json.loads(out.read_text(encoding="utf-8")) if out else None
        return json.loads(r.stdout), written

    def reduce(self, request: Dict[str, Any]) -> Dict[str, Any]:
        return self._with_input("--reduce", request)[0]

    def assign_ids(self, request: Dict[str, Any]) -> Dict[str, Any]:
        return self._with_input("--assign-ids", request)[0]

    def seal(self, request: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        out, artifact = self._with_input("--reduce", request, ("--emit-artifact",), "artifact.json")
        assert artifact is not None
        return out, artifact

    def print_policy(self, overlay: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if overlay:
            return self._with_input("--print-policy", overlay)[0]
        r = self._run("--print-policy")
        if r.returncode != 0:
            raise OverturnError(f"overturn --print-policy failed: {r.stderr.strip()}", r.returncode, r.stderr)
        return json.loads(r.stdout)

    def default_policy(self) -> Dict[str, Any]:
        if self._default_policy is None:
            self._default_policy = self.print_policy()["policy"]
        return json.loads(json.dumps(self._default_policy))

    def version(self) -> Dict[str, Any]:
        r = self._run("--version")
        if r.returncode != 0:
            raise OverturnError(f"overturn --version failed (a reducer older than this package?): {r.stderr.strip()}",
                            r.returncode, r.stderr)
        return json.loads(r.stdout)

    def replay(self, artifact: Dict[str, Any]) -> VerifyResult:
        with tempfile.TemporaryDirectory(prefix="overturn-") as d:
            p = Path(d) / "artifact.json"
            p.write_text(json.dumps(artifact, sort_keys=True, indent=1), encoding="utf-8")
            r = self._run("--replay-from", str(p), "--json")
        try:
            res = json.loads(r.stdout)
        except ValueError:
            return VerifyResult(False, "error", r.returncode, r.stderr.strip().replace(str(p), "<artifact>"))
        msg = str(res.get("message", "")).replace(str(p), "<artifact>")
        if res.get("ok"):
            return VerifyResult(True, None, 0, msg, res.get("certificate"))
        return VerifyResult(False, _REASONS.get(res.get("reason") or "", "error"), r.returncode, msg)


#: ``--replay-from --json`` reason -> ``VerifyResult.reason``.
_REASONS = {
    "io": "parse", "parse": "parse", "format": "format",
    "artifact_hash": "artifact_hash", "record_hash": "artifact_hash", "contribution_id": "artifact_hash",
    "policy_hash": "policy_hash", "output": "output", "envelope": "envelope",
}


_default: Optional[Backend] = None


def default_backend() -> Backend:
    global _default
    if _default is None:
        _default = SubprocessBackend()
    return _default


def set_default_backend(backend: Optional[Backend]) -> None:
    """Install a backend for calls that do not pass one (``None`` resets)."""
    global _default
    _default = backend
