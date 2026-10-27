"""校验线上前端资源完整性，并给出需要重传的文件。

用法：python scripts/verify_assets.py <remote-host-alias>
说明：通过 ssh 读取服务器文件大小，与本地 dist/assets 对比；
      任何大小不一致或缺失的文件都会列出来（上传中断会导致 JS 被截断，
      站点报 SyntaxError: Unexpected end of input 或白屏）。
"""
import subprocess
import sys
from pathlib import Path

KEY = str(Path.home() / ".ssh" / "menduner_deploy")
HOST = "admin@47.116.133.230"
REMOTE = "/srv/menduner/frontend-dist/assets"
LOCAL = Path(__file__).resolve().parent.parent / "frontend" / "dist" / "assets"


def remote_sizes() -> dict[str, int]:
    result = subprocess.run(
        ["ssh", "-i", KEY, "-o", "BatchMode=yes", HOST, f"ls -l {REMOTE}"],
        capture_output=True, text=True, encoding="utf-8",
    )
    sizes: dict[str, int] = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 9 and parts[-1] not in (".", ".."):
            try:
                sizes[parts[-1]] = int(parts[4])
            except ValueError:
                continue
    return sizes


def main() -> int:
    sizes = remote_sizes()
    local = {p.name: p.stat().st_size for p in LOCAL.iterdir() if p.is_file()}
    print(f"  本地 {len(local)} 个文件 | 服务器 {len(sizes)} 个文件")
    bad = [name for name, size in local.items() if sizes.get(name) != size]
    extra = [name for name in sizes if name not in local]
    for name in bad:
        print(f"  ✗ 大小不一致/缺失: {name} 本地={local[name]} 线上={sizes.get(name)}")
    for name in extra:
        print(f"  · 线上多余: {name}")
    print(f"  需要重传 {len(bad)} 个")
    (Path(__file__).resolve().parent.parent / ".bad-assets.txt").write_text("\n".join(bad), encoding="utf-8")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
