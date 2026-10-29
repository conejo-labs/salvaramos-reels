import argparse
import os
import shutil
import sys
from pathlib import Path

from probe import probe
from project import load
from util import MEDIA, ROOT, ffmpeg, run

DRIVE = os.environ.get("SALVARAMOS_DRIVE", "salvaramos:SalvaRamos Reels")
WHATSAPP_MB = 15.0
WHATSAPP_AUDIO_KBPS = 96


def rclone_bin() -> str:
    found = shutil.which("rclone") or str(Path.home() / ".local/bin/rclone")
    if not Path(found).exists():
        sys.exit("No encuentro rclone. Instálalo y conecta Google Drive como dice el README (sección «Material»).")
    return found


def copy(source: str | Path, destination: str | Path) -> None:
    run([rclone_bin(), "copy", source, destination, "--progress"])


def pull(event: str) -> None:
    copy(f"{DRIVE}/eventos/{event}/raw", MEDIA / "eventos" / event / "raw")
    copy(f"{DRIVE}/memes/pack", MEDIA / "memes" / "pack")
    copy(f"{DRIVE}/sfx/pack", MEDIA / "sfx" / "pack")


def upload(event: str) -> None:
    local = MEDIA / "eventos" / event / "raw"
    if not local.is_dir():
        sys.exit(f"No hay raws locales en {local.relative_to(ROOT)}")
    copy(local, f"{DRIVE}/eventos/{event}/raw")


def upload_memes() -> None:
    copy(MEDIA / "memes" / "pack", f"{DRIVE}/memes/pack")


def upload_sfx() -> None:
    copy(MEDIA / "sfx" / "pack", f"{DRIVE}/sfx/pack")


def whatsapp_version(video: Path) -> Path:
    output = video.with_name(f"{video.stem}-wsp.mp4")
    seconds = probe(video)["duration"]
    video_kbps = int(WHATSAPP_MB * 8 * 1024 / seconds - WHATSAPP_AUDIO_KBPS - 14)
    passlog = video.with_name(f"{video.stem}-wsp-pass")
    encode = ["-vf", "scale=720:1280:flags=lanczos", "-c:v", "libx264", "-preset", "slow", "-b:v", f"{video_kbps}k",
              "-passlogfile", passlog]
    ffmpeg("-i", video, *encode, "-pass", 1, "-an", "-f", "null", os.devnull)
    ffmpeg("-i", video, *encode, "-pass", 2, "-maxrate", f"{video_kbps * 3 // 2}k", "-bufsize", f"{video_kbps * 3}k",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", f"{WHATSAPP_AUDIO_KBPS}k", "-ac", 2,
           "-movflags", "+faststart", output)
    for leftover in video.parent.glob(f"{passlog.name}*"):
        leftover.unlink()
    return output


def deliver(project_dir: Path, upload_to_drive: bool) -> None:
    project = load(project_dir)
    video = project.build / f"{project.slug}.mp4"
    if not video.exists():
        sys.exit(f"Primero renderiza: .venv/bin/python src/render.py {project_dir}")
    compressed = whatsapp_version(video)
    print(f"{compressed.relative_to(ROOT)} ({compressed.stat().st_size / 1048576:.1f} MB)")
    if upload_to_drive:
        for file in (video, compressed):
            copy(file, f"{DRIVE}/entregas/{project.event}")


def main() -> None:
    parser = argparse.ArgumentParser(description=f"Material compartido en Google Drive ({DRIVE})")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("pull", help="baja los raws de un evento y los packs de memes y efectos").add_argument("event")
    commands.add_parser("upload", help="sube a Drive los raws locales de un evento").add_argument("event")
    commands.add_parser("upload-memes", help="sube a Drive el pack de memes local")
    commands.add_parser("upload-sfx", help="sube a Drive el pack de efectos local")
    deliver_parser = commands.add_parser("deliver", help="versión para WhatsApp y subida a entregas/")
    deliver_parser.add_argument("project", type=Path)
    deliver_parser.add_argument("--local", action="store_true", help="solo comprime, no sube a Drive")
    args = parser.parse_args()
    if args.command == "pull":
        pull(args.event)
    elif args.command == "upload":
        upload(args.event)
    elif args.command == "upload-memes":
        upload_memes()
    elif args.command == "upload-sfx":
        upload_sfx()
    else:
        deliver(args.project, upload_to_drive=not args.local)


if __name__ == "__main__":
    main()
