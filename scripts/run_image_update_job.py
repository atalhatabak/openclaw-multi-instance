#!/usr/bin/env python3
from __future__ import annotations

import argparse
import codecs
import os
import subprocess
import sys
import traceback
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import db
from models import operation_log_model
from services.log_service import append_log_text
from services.version_service import detect_image_version, image_exists, prune_managed_images, set_current_image_state


CLONE_PATCH_BUILD_SCRIPT = ROOT_DIR / "clone_patch_build.sh"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run image update job in a detached process.")
    parser.add_argument("--log-id", type=int, required=True)
    parser.add_argument("--log-path", required=True)
    parser.add_argument("--image-ref", required=True)
    parser.add_argument("--target-version", required=True)
    parser.add_argument("--version-source", default="manual")
    parser.add_argument("--pid-path", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db.init_db()

    log_id = int(args.log_id)
    log_path = Path(args.log_path)
    pid_path = Path(args.pid_path)

    try:
        pid_path.write_text(f"{os.getpid()}\n", encoding="ascii")
    except OSError:
        pass

    status = "error"
    try:
        process = subprocess.Popen(
            ["bash", str(CLONE_PATCH_BUILD_SCRIPT)],
            cwd=str(ROOT_DIR),
            env=os.environ.copy(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
        )
        _stream_output(process, log_path)
        returncode = process.wait()
        if returncode != 0:
            append_log_text(
                log_path,
                f"\n---- RESULT ----\nBuild basarisiz tamamlandi. Exit code: {returncode}\n",
            )
        elif not image_exists(args.image_ref):
            append_log_text(
                log_path,
                "\n---- RESULT ----\n"
                f"Build tamamlandi ancak hedef image yerelde bulunamadi: {args.image_ref}\n"
                "Muhtemelen env.base icindeki OPENCLAW_IMAGE degeri build sirasinda override etti.\n",
            )
        else:
            effective_version = detect_image_version(args.image_ref) or args.target_version
            updated_image = set_current_image_state(
                image_ref=args.image_ref,
                version=effective_version,
                version_source=args.version_source,
            )
            prune_result = prune_managed_images(retain=3, protected_refs={updated_image.image_ref})
            status = "success"
            append_log_text(
                log_path,
                "\n---- RESULT ----\n"
                f"Image guncellendi. Ref: {updated_image.image_ref} | Version: {updated_image.version}\n"
                f"{_format_prune_result(prune_result)}\n",
            )
        operation_log_model.update_operation_log_status(log_id, status=status)
    except Exception:
        append_log_text(
            log_path,
            "\n---- INTERNAL ERROR ----\n"
            f"{traceback.format_exc()}\n",
        )
        operation_log_model.update_operation_log_status(log_id, status="error")
    finally:
        try:
            pid_path.unlink(missing_ok=True)
        except OSError:
            pass

    return 0


def _stream_output(process: subprocess.Popen[bytes], log_path: Path) -> None:
    if process.stdout is None:
        return

    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    with process.stdout:
        while True:
            chunk = process.stdout.read(4096)
            if not chunk:
                break
            text = decoder.decode(chunk)
            if text:
                append_log_text(log_path, _normalize_stream_text(text))

        remainder = decoder.decode(b"", final=True)
        if remainder:
            append_log_text(log_path, _normalize_stream_text(remainder))


def _normalize_stream_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _format_prune_result(result: dict[str, list[dict[str, str]]]) -> str:
    removed = result.get("removed") or []
    skipped = result.get("skipped") or []
    parts: list[str] = []
    if removed:
        parts.append("Silinen image'lar: " + ", ".join(item["image_ref"] for item in removed))
    if skipped:
        parts.append(
            "Korunan/atlanan image'lar: "
            + ", ".join(f"{item['image_ref']} ({item['reason']})" for item in skipped)
        )
    if not parts:
        return "Rotate sonucu: prune gerekmedi."
    return "Rotate sonucu: " + " | ".join(parts)


if __name__ == "__main__":
    raise SystemExit(main())
