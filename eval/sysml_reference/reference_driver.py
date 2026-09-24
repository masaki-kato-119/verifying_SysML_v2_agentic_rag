"""Driver for running SysML v2 text through the OMG SysML v2 Pilot
Implementation ("reference implementation") for comparison against
sysml_v2_checker_advanced.

How this works
---------------
The OMG SysML v2 Pilot Implementation is normally consumed either as an
Eclipse/Xtext plugin or as a Jupyter kernel (the ``jupyter-sysml-kernel``
conda-forge package). Both of those front ends are thin wrappers around a
single Java class, ``org.omg.sysml.interactive.SysMLInteractive``, which
exposes a simple parse/validate API:

    SysMLInteractive si = SysMLInteractive.getInstance();
    si.loadLibrary(pathToSysmlLibrary);
    SysMLInteractiveResult result = si.process(sourceText, false);
    result.getIssues();  // List<org.eclipse.xtext.validation.Issue>

``vendor/RefDriver.java`` (compiled to ``vendor/RefDriver.class``) is a tiny
standalone Java program that calls exactly that API: given a library
directory and a source file, it parses + validates the file and prints a
single line of JSON with the resulting diagnostics. This module just shells
out to ``java`` to run that driver and translates its output into the
dict shape used by the rest of the eval harness.

Two ways to call it:

- ``run_reference_check(text)`` starts one JVM per call. Simple, fully
  isolated, and about 13 seconds a sample because ``si.loadLibrary()`` runs
  every time.
- ``ReferenceBatch`` keeps one JVM alive and feeds it paths on stdin, paying
  the library load once. **Verified 2026-09-05 to produce diagnostics
  identical to the per-call mode across all 730 corpus samples** (zero
  mismatches; see ``scripts/compare_reference_runs_batch_vs_serial.py``).
  Re-run that verification if the jar or the sample corpus changes.

Setup (already done once for this checkout; see eval/sysml_reference/):
  - vendor/jupyter-sysml-kernel-<version>-pyhd8ed1ab_0.conda downloaded from
    conda-forge (contains the fat jar with the parser/validator). The version
    in use is REFERENCE_VERSION below.
  - vendor/_extracted/.../jupyter-sysml-kernel-<version>-all.jar extracted from
    that package (a plain ZIP containing zstd-compressed tarballs).
  - sysml.library/ checked out from the Systems-Modeling/SysML-v2-Release
    GitHub repo (sparse checkout of just the sysml.library/ subtree).
    **The .conda ships the matching sysml.library too** (share/jupyter/kernels/
    sysml/sysml.library/, 95 files), so the checkout is not the only source --
    and it is the authoritative pairing if the two ever disagree. Verified
    2026-09-24: the checkout matches the bundled copy byte for byte once CRLF
    is normalised, and the bundled library is *identical* between 0.61.0 and
    0.62.0, so that upgrade needed no library change.
  - vendor/RefDriver.java compiled to vendor/RefDriver.class with javac
    against the fat jar's classpath.

If you need to recompile RefDriver.class (e.g. after editing RefDriver.java):
    javac -cp <path-to-fat-jar> -d eval/sysml_reference/vendor \
        eval/sysml_reference/vendor/RefDriver.java
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
VENDOR_DIR = HERE / "vendor"

# 参照実装のバージョン。**ここを変えたら必ず以下をやり直すこと**:
#   1. 対応する .conda を取得して jar を展開し直す（下の Setup 節の手順）
#   2. RefDriver.class を新しい jar のクラスパスで再コンパイル
#   3. バッチモードが逐次モードと一致するかを測り直す
#      （scripts/compare_reference_runs_batch_vs_serial.py）
#   4. 730件を流し直し、旧バージョンの結果と突き合わせる
# 上げ忘れると「古い jar で測った数字を新しいバージョンのものとして報告する」
# 形の静かな誤りになるため、パスに版を直書きして存在しなければ落ちるようにしてある
# （glob で拾うと、古い jar が残っているときに黙ってそちらを使ってしまう）。
REFERENCE_VERSION = "0.62.0"
EXTRACTED_JAR = (
    VENDOR_DIR
    / "_extracted"
    / "share"
    / "jupyter"
    / "kernels"
    / "sysml"
    / f"jupyter-sysml-kernel-{REFERENCE_VERSION}-all.jar"
)
LIBRARY_DIR = HERE / "sysml.library"
DRIVER_CLASS_DIR = VENDOR_DIR  # RefDriver.class lives directly in vendor/


class ReferenceSetupError(RuntimeError):
    """Raised when the reference implementation isn't set up correctly."""


# Markers that mean si.loadLibrary() did not fully load the standard library.
# Measured 2026-09-04: when several JVMs read eval/sysml_reference/sysml.library
# at the same time, EMF can fail to demand-load a library resource and reports
# e.g. "FileNotFoundException: ...sysml.library\Kernel%20Libraries\..." (the
# space in the library's own directory name left URI-encoded). RefDriver returns
# crashed:true when that aborts the load outright -- but a load that only
# partially fails leaves the driver returning issues:[] as if the file were
# clean, which is indistinguishable from a genuinely clean file and silently
# corrupts a comparison run. So: if any of these appear on stderr, the library
# was not in a known-good state and the diagnostics from that process must not
# be trusted, no matter how many were reported.
_LIBRARY_LOAD_FAILURE_MARKERS = (
    "FileNotFoundException",
    "DiagnosticWrappedException",
    "handleDemandLoadException",
)


def _library_load_failed(stderr: str) -> str | None:
    """Return the offending marker if stderr shows a library-load failure."""
    for marker in _LIBRARY_LOAD_FAILURE_MARKERS:
        if marker in stderr:
            return marker
    return None


# A snippet the reference implementation must reject. Used as a canary: if this
# comes back with no error-severity diagnostic, the reference is not actually
# validating anything and every result from that process is worthless.
CANARY_SOURCE = "package P { part def }"


def run_canary(timeout: float = 60.0) -> tuple[bool, str]:
    """Check that the reference implementation still reports errors at all.

    Returns (ok, detail). ok is True only when the canary snippet came back
    with at least one error-severity diagnostic.
    """
    result = run_reference_check(CANARY_SOURCE, timeout=timeout)
    if result["crashed"]:
        excerpt = (result.get("raw_stderr") or "").strip()[-300:]
        return False, f"canary crashed: {excerpt}"
    errors = [d for d in result["diagnostics"] if (d.get("severity") or "").lower() == "error"]
    if not errors:
        return False, (
            "canary returned no error-severity diagnostic for "
            f"{CANARY_SOURCE!r} -- the reference implementation is not validating"
        )
    return True, f"canary ok ({len(errors)} error diagnostics)"


def _find_java() -> str:
    java = shutil.which("java")
    if java:
        return java
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        candidate = Path(java_home) / "bin" / ("java.exe" if os.name == "nt" else "java")
        if candidate.is_file():
            return str(candidate)
    raise ReferenceSetupError(
        "Could not find a 'java' executable on PATH and JAVA_HOME is not set. "
        "Install a JDK (21+) or add one to PATH."
    )


def _check_setup() -> None:
    if not EXTRACTED_JAR.is_file():
        raise ReferenceSetupError(
            f"Reference implementation jar not found at {EXTRACTED_JAR}. "
            "Download+extract the jupyter-sysml-kernel conda-forge package first."
        )
    if not LIBRARY_DIR.is_dir():
        raise ReferenceSetupError(
            f"sysml.library not found at {LIBRARY_DIR}. "
            "Sparse-checkout it from Systems-Modeling/SysML-v2-Release first."
        )
    if not (DRIVER_CLASS_DIR / "RefDriver.class").is_file():
        raise ReferenceSetupError(
            f"RefDriver.class not found in {DRIVER_CLASS_DIR}. Compile it with: "
            f'javac -cp "{EXTRACTED_JAR}" -d "{DRIVER_CLASS_DIR}" '
            f'"{DRIVER_CLASS_DIR / "RefDriver.java"}"'
        )


RESULT_PREFIX = "@@REFDRIVER@@"


class ReferenceBatch:
    """Keep one RefDriver JVM alive and feed it file paths, one per line.

    Single-file mode spends about 13 seconds per sample on JVM startup plus
    ``si.loadLibrary()``; batch mode pays that once. Use it as a context
    manager::

        with ReferenceBatch() as batch:
            for path in paths:
                result = batch.check_file(path)

    The result dicts have the same shape ``run_reference_check`` returns, so
    callers can swap between the two.

    **Do not treat batch results as interchangeable with serial ones without
    checking.** ``SysMLInteractive`` is the Jupyter kernel's session API, and
    consecutive ``process()`` calls are cells of one session; RefDriver calls
    ``removeResource()`` after each file to drop the previous declarations, but
    whether that fully isolates files is an empirical question. The two modes
    were compared over all 730 samples before batch mode was used for anything
    (see ``scripts/compare_reference_runs_batch_vs_serial.py``).

    Not thread-safe, and deliberately so: one JVM answers one request at a time.
    Running several of these in parallel would reintroduce the library-load
    failures that made concurrent single-file runs unusable.
    """

    def __init__(self, timeout: float = 300.0) -> None:
        _check_setup()
        self._timeout = timeout
        self._proc = None

    def __enter__(self) -> "ReferenceBatch":
        java = _find_java()
        classpath = f"{DRIVER_CLASS_DIR}{os.pathsep}{EXTRACTED_JAR}"
        self._proc = subprocess.Popen(
            [java, "-cp", classpath, "RefDriver", str(LIBRARY_DIR), "--batch"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        if self._proc is None:
            return
        try:
            if self._proc.stdin is not None:
                self._proc.stdin.close()
            self._proc.wait(timeout=30)
        except Exception:  # noqa: BLE001 -- 終了処理。相手のJVMがどう死んでいてもkillへ倒す
            self._proc.kill()
        finally:
            self._proc = None

    def check_file(self, source_path: str) -> dict[str, Any]:
        """Send one path and read back its result line."""
        if self._proc is None or self._proc.poll() is not None:
            return {
                "success": False,
                "diagnostics": [],
                "raw_stderr": "[batch process is not running]",
                "crashed": True,
            }
        try:
            self._proc.stdin.write(str(source_path) + "\n")
            self._proc.stdin.flush()
        except Exception as exc:  # noqa: BLE001 -- 相手のJVMが落ちている場合を含む
            return {
                "success": False,
                "diagnostics": [],
                "raw_stderr": f"[failed to send path: {exc!r}]",
                "crashed": True,
            }

        # Skip anything the JVM or its libraries print on their own; only lines
        # carrying RESULT_PREFIX are answers.
        while True:
            line = self._proc.stdout.readline()
            if line == "":
                return {
                    "success": False,
                    "diagnostics": [],
                    "raw_stderr": "[batch process closed stdout before answering]",
                    "crashed": True,
                }
            if line.startswith(RESULT_PREFIX):
                payload = line[len(RESULT_PREFIX):].strip()
                break

        return _normalize_driver_json(payload, raw_stderr="")

    def run_canary(self) -> tuple[bool, str]:
        """Same health check as the module-level run_canary, over the batch."""
        import tempfile

        fd, tmp = tempfile.mkstemp(suffix=".sysml")
        os.close(fd)
        try:
            Path(tmp).write_text(CANARY_SOURCE, encoding="utf-8")
            result = self.check_file(tmp)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        if result["crashed"]:
            return False, f"batch canary crashed: {(result.get('raw_stderr') or '')[-200:]}"
        errors = [d for d in result["diagnostics"] if (d.get("severity") or "").lower() == "error"]
        if not errors:
            return False, "batch canary returned no error-severity diagnostic"
        return True, f"batch canary ok ({len(errors)} error diagnostics)"


def _normalize_driver_json(payload: str, raw_stderr: str) -> dict[str, Any]:
    """Turn one RefDriver JSON line into the dict shape callers expect."""
    marker = _library_load_failed(raw_stderr)
    if marker is not None:
        return {
            "success": False,
            "diagnostics": [],
            "raw_stderr": raw_stderr + f"\n[library load failure detected ({marker})]",
            "crashed": True,
        }
    try:
        result = json.loads(payload)
    except json.JSONDecodeError as exc:
        return {
            "success": False,
            "diagnostics": [],
            "raw_stderr": raw_stderr + f"\n[JSON decode error: {exc}]\n{payload}",
            "crashed": True,
        }
    if result.get("crashed"):
        return {
            "success": False,
            "diagnostics": [],
            "raw_stderr": raw_stderr + "\n" + (result.get("exception") or ""),
            "crashed": True,
        }
    diagnostics = [
        {
            "severity": issue.get("severity"),
            "line": issue.get("line"),
            "message": issue.get("message"),
        }
        for issue in result.get("issues", [])
    ]
    return {
        "success": bool(result.get("success")),
        "diagnostics": diagnostics,
        "raw_stderr": raw_stderr,
        "crashed": False,
    }


def run_reference_check(sysml_text: str, timeout: float = 30.0) -> dict[str, Any]:
    """Run sysml_text through the OMG SysML v2 Pilot Implementation.

    Returns:
        {
            "success": bool,               # True iff no ERROR-severity issues
            "diagnostics": [                # one entry per issue reported
                {"severity": str, "line": int | None, "message": str}, ...
            ],
            "raw_stderr": str,              # stderr from the java process
                                             # (JVM warnings, log4j noise, and
                                             # on crash, the java stack trace)
            "crashed": bool,                # True if the driver could not
                                             # produce a diagnostics result at
                                             # all (timeout, JVM crash, setup
                                             # error, bad output, ...)
        }
    """
    _check_setup()
    java = _find_java()

    fd, tmp_path_str = tempfile.mkstemp(suffix=".sysml")
    os.close(fd)
    tmp_path = Path(tmp_path_str)
    try:
        tmp_path.write_text(sysml_text, encoding="utf-8")

        classpath = f"{DRIVER_CLASS_DIR}{os.pathsep}{EXTRACTED_JAR}"
        cmd = [java, "-cp", classpath, "RefDriver", str(LIBRARY_DIR), str(tmp_path)]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            stderr = exc.stderr or ""
            return {
                "success": False,
                "diagnostics": [],
                "raw_stderr": f"[TIMEOUT after {timeout}s]\n{stderr}",
                "crashed": True,
            }

        raw_stderr = proc.stderr or ""
        stdout = (proc.stdout or "").strip()

        # RefDriver prints exactly one JSON object as its final stdout line.
        json_line = None
        for line in stdout.splitlines():
            line = line.strip()
            if line.startswith("{"):
                json_line = line

        if json_line is None:
            return {
                "success": False,
                "diagnostics": [],
                "raw_stderr": (
                    raw_stderr
                    + f"\n[RefDriver produced no JSON on stdout; exit code {proc.returncode}]\n"
                    + stdout
                ),
                "crashed": True,
            }

        try:
            result = json.loads(json_line)
        except json.JSONDecodeError as exc:
            return {
                "success": False,
                "diagnostics": [],
                "raw_stderr": raw_stderr + f"\n[JSON decode error: {exc}]\n{json_line}",
                "crashed": True,
            }

        if result.get("crashed"):
            return {
                "success": False,
                "diagnostics": [],
                "raw_stderr": raw_stderr + "\n" + (result.get("exception") or ""),
                "crashed": True,
            }

        # The driver said it completed, but the standard library may not have
        # loaded cleanly -- in which case the diagnostics are meaningless (and
        # an empty list looks exactly like a clean file). Treat that as a crash
        # so callers discard it instead of recording it as a result.
        marker = _library_load_failed(raw_stderr)
        if marker is not None:
            return {
                "success": False,
                "diagnostics": [],
                "raw_stderr": (
                    raw_stderr
                    + f"\n[library load failure detected on stderr ({marker}); "
                    "diagnostics discarded as untrustworthy]"
                ),
                "crashed": True,
            }

        diagnostics = [
            {
                "severity": issue.get("severity"),
                "line": issue.get("line"),
                "message": issue.get("message"),
            }
            for issue in result.get("issues", [])
        ]

        return {
            "success": bool(result.get("success")),
            "diagnostics": diagnostics,
            "raw_stderr": raw_stderr,
            "crashed": False,
        }
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python reference_driver.py <file.sysml>", file=sys.stderr)
        sys.exit(2)

    path = Path(sys.argv[1])
    text = path.read_text(encoding="utf-8")

    try:
        result = run_reference_check(text)
    except ReferenceSetupError as exc:
        print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        sys.exit(3)

    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result["success"] and not result["crashed"] else 1)


if __name__ == "__main__":
    main()
