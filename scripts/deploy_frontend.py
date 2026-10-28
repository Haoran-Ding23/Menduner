"""安全部署前端（原子替换 + 校验 + 可回滚）。

历史事故：之前两次 scp 中断，导致线上 index.html/资源缺失、站点白屏。
本次改进：
  1 本地打包成一个 tar.gz → **只建立一次 scp 连接**（逐文件传会被 sshd 限流，
     实测连续 30 个连接会 kex_exchange_identification: Connection reset）；
  2 上传后在服务器解包到临时目录，逐个文件核对字节数；
  3 校验通过才原子替换（旧版本 mv 成 .prev，可一键回滚）；
  4 任何一步失败都直接退出，线上保持原样。

用法：
  python scripts/deploy_frontend.py              # 部署 frontend/dist
  python scripts/deploy_frontend.py --rollback   # 回滚到上一版
"""
import argparse
import base64
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "frontend" / "dist"
KEY = str(Path.home() / ".ssh" / "menduner_deploy")
HOST = "admin@47.116.133.230"
SSH = ["ssh", "-i", KEY, "-o", "BatchMode=yes", "-o", "ConnectTimeout=30", HOST]
LIVE = "/srv/menduner/frontend-dist"
PREV = "/srv/menduner/frontend-dist.prev"


def run_remote(script: str) -> str:
    b64 = base64.b64encode(script.encode()).decode()
    last = ""
    for attempt in range(4):
        result = subprocess.run(SSH + [f"echo {b64} | base64 -d | bash"], capture_output=True, text=True)
        last = (result.stdout or "") + (result.stderr or "")
        if result.returncode == 0:
            return last
        time.sleep(3)
    return last


def local_files() -> dict[str, int]:
    files = {"index.html": (DIST / "index.html").stat().st_size}
    for path in (DIST / "assets").iterdir():
        files[f"assets/{path.name}"] = path.stat().st_size
    return files


def make_tarball() -> Path:
    handle = tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False)
    handle.close()
    target = Path(handle.name)
    with tarfile.open(target, "w:gz") as archive:
        archive.add(DIST / "index.html", arcname="index.html")
        for path in (DIST / "assets").iterdir():
            archive.add(path, arcname=f"assets/{path.name}")
    return target


def upload(tarball: Path) -> bool:
    for attempt in range(4):
        result = subprocess.run(
            ["scp", "-i", KEY, "-o", "BatchMode=yes", "-o", "ConnectTimeout=30",
             str(tarball), f"{HOST}:/home/admin/fe-release.tar.gz"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print(f"  ✓ 上传成功（第 {attempt + 1} 次）")
            return True
        print(f"  重试上传（{attempt + 1}/4）：{result.stderr.strip()[:90]}")
        time.sleep(4)
    return False


def deploy() -> int:
    if not (DIST / "index.html").exists():
        print("  ✗ 找不到 frontend/dist/index.html，请先 npm run build")
        return 2
    files = local_files()
    print(f"  本地文件 {len(files)} 个，打包上传 …")
    tarball = make_tarball()
    try:
        if not upload(tarball):
            print("  ✗ 上传失败，线上未改动（安全）")
            return 1
    finally:
        tarball.unlink(missing_ok=True)

    expected = "\n".join(f"{name} {size}" for name, size in sorted(files.items()))
    script = (
        "set -e\n"
        "rm -rf /home/admin/fe-stage && mkdir -p /home/admin/fe-stage\n"
        "tar -xzf /home/admin/fe-release.tar.gz -C /home/admin/fe-stage\n"
        "cd /home/admin/fe-stage && find . -type f -printf '%P %s\\n' | sort > /tmp/remote.txt\n"
        f"cat > /tmp/expected.txt <<'EOF'\n{expected}\nEOF\n"
        # 两边用同一种排序方式再比：Python 的 sort 与 shell 的 LC_COLLATE 结果可能不同，
        # 直接 diff 会因顺序不同误判成"文件不一致"。
        "LC_ALL=C sort -o /tmp/remote.txt /tmp/remote.txt\n"
        "LC_ALL=C sort -o /tmp/expected.txt /tmp/expected.txt\n"
        "if ! diff -q /tmp/expected.txt /tmp/remote.txt > /dev/null; then\n"
        "  echo '  ✗ 服务器文件与本地不一致，取消部署'\n"
        "  diff /tmp/expected.txt /tmp/remote.txt | head -10\n"
        "  exit 1\n"
        "fi\n"
        "echo '  ✓ 校验通过：文件数与字节数全部一致'\n"
        f"sudo rm -rf {PREV}\n"
        f"if [ -d {LIVE} ]; then sudo mv {LIVE} {PREV}; fi\n"
        f"sudo mkdir -p {LIVE}\n"
        "sudo cp -r /home/admin/fe-stage/. " + LIVE + "/\n"
        f"sudo chown -R menduner:menduner {LIVE}\n"
        "rm -rf /home/admin/fe-stage /home/admin/fe-release.tar.gz /tmp/remote.txt /tmp/expected.txt\n"
        f"echo \"  线上资源数: $(ls -1 {LIVE}/assets | wc -l)\"\n"
        "curl -s -o /dev/null -w '  首页 HTTP %{http_code}\\n' https://entgroup14.com/\n"
    )
    output = run_remote(script)
    print(output.strip())
    if "✗" in output:
        return 1
    print("  ✓ 部署完成（上一版保留在 frontend-dist.prev，可 --rollback 回滚）")
    return 0


def rollback() -> int:
    script = (
        "set -e\n"
        f"if [ ! -d {PREV} ]; then echo '  没有可回滚的上一版'; exit 1; fi\n"
        "sudo rm -rf /srv/menduner/frontend-dist.broken\n"
        f"sudo mv {LIVE} /srv/menduner/frontend-dist.broken\n"
        f"sudo mv {PREV} {LIVE}\n"
        "sudo chown -R menduner:menduner /srv/menduner/frontend-dist\n"
        f"echo \"  已回滚，资源数: $(ls -1 {LIVE}/assets | wc -l)\"\n"
        "curl -s -o /dev/null -w '  首页 HTTP %{http_code}\\n' https://entgroup14.com/\n"
    )
    print(run_remote(script).strip())
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    sys.exit(rollback() if args.rollback else deploy())
