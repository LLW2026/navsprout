"""Run browser acceptance on a disposable loopback instance, never a live catalog."""
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix="navsprout-check-") as scratch:
        scratch = Path(scratch)
        # Exercise the documented setup with an isolated HOME and project copy.
        project = scratch / "project"
        (project / "scripts").mkdir(parents=True)
        (project / "scripts/setup.py").write_bytes((ROOT / "scripts/setup.py").read_bytes())
        with socket.socket() as port_socket:
            port_socket.bind(("127.0.0.1", 0))
            port = port_socket.getsockname()[1]
        setup_env = {**os.environ, "HOME": str(scratch / "home")}
        subprocess.run([sys.executable, str(project / "scripts/setup.py"), "--port", str(port)], env=setup_env, check=True, stdout=subprocess.DEVNULL)
        values = dict(line.split("=", 1) for line in (project / ".env").read_text().splitlines())
        values = {key: value.strip("'") for key, value in values.items()}
        assert values["NAV_ALLOWED_HOSTS"] == "localhost,127.0.0.1"
        assert values["NAV_HTTPS_HOSTS"] == ""
        assert "https://" not in values["NAV_ALLOWED_ORIGINS"]
        assert (project / ".env").stat().st_mode & 0o777 == 0o600
        password = (scratch / "home/.config/navsprout/admin-password.txt").read_text().strip()
        values.update(NAV_DB=str(project / "data/nav.db"), NAV_BACKGROUND_ENABLED="false")
        base = f"http://127.0.0.1:{port}"
        environment = {**os.environ, **values, "NAV_TEST_URL": base, "NAV_ORDER_ISOLATED": "1", "NAV_TEST_PASSWORD": password, "NAV_TEST_API_TOKEN": values["NAV_API_TOKEN"]}
        (ROOT / "artifacts").mkdir(exist_ok=True)
        with (ROOT / "artifacts/browser-server.log").open("w") as log:
            process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:create_app", "--factory", "--host", "127.0.0.1", "--port", str(port), "--no-access-log"], cwd=ROOT, env=environment, stdout=log, stderr=log)
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError("Temporary server exited; see artifacts/browser-server.log")
                    try:
                        with urllib.request.urlopen(base + "/healthz", timeout=1):
                            break
                    except (OSError, urllib.error.URLError):
                        time.sleep(0.1)
                else:
                    raise RuntimeError("Temporary server did not start")
                print("PASS 隔离初始化：随机密码、受保护配置、仅本机允许来源", flush=True)
                subprocess.run(["node", "tests/appearance-order.cjs"], cwd=ROOT, env=environment, check=True)
                categories = ["我的应用", "开发工具", "工作网站", "常用资料", "设计灵感", "工具收藏"]
                names = ["项目看板", "文档助手", "服务监控", "文件管理", "工作台", "任务清单", "日程安排", "资料检索", "代码仓库", "数据报告", "图片工具", "消息中心"]
                icons = ["看", "文", "监", "档", "工", "任", "日", "搜", "码", "报", "图", "信"]
                for ci, category in enumerate(categories):
                    for index, name in enumerate(names):
                        payload = {"key": f"demo-{ci}-{index}", "name": name, "url": f"https://app-{ci}-{index}.example.com", "category": category, "description": "示例：" + category + "中的" + name, "icon": icons[index], "organization": "个人" if ci < 2 else "工作", "network": "lan" if index % 3 == 0 else "public", "environment": "test" if index % 4 == 0 else "production", "pinned": ci == 0 and index < 3, "sort_order": index * 10}
                        request = urllib.request.Request(base + "/api/v1/links", data=json.dumps(payload, ensure_ascii=False).encode(), headers={"Authorization": "Bearer " + values["NAV_API_TOKEN"], "Content-Type": "application/json"})
                        with urllib.request.urlopen(request, timeout=10):
                            pass
                subprocess.run(["node", "tests/responsive.cjs"], cwd=ROOT, env=environment, check=True)
                print("PASS 浏览器验收完成；所有网址与截图均来自临时示例数据", flush=True)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    main()
