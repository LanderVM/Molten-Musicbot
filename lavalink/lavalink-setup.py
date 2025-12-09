import sys
import subprocess
import requests
import signal
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
LAVALINK_DIR = SCRIPT_DIR
JAR_NAME = "Lavalink.jar"
LAVALINK_JAR = LAVALINK_DIR / JAR_NAME
GITHUB_API_RELEASES = "https://api.github.com/repos/lavalink-devs/Lavalink/releases/latest"

def get_latest_lavalink_url():
    resp = requests.get(GITHUB_API_RELEASES, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    for asset in data.get("assets", []):
        if asset.get("name", "").endswith(".jar"):
            return asset["browser_download_url"], asset["name"]
    raise RuntimeError("Could not find Lavalink .jar in latest release assets.")

def ensure_lavalink():
    LAVALINK_DIR.mkdir(exist_ok=True)
    target = LAVALINK_DIR / JAR_NAME
    if target.exists():
        print("✅ Lavalink.jar already present.")
        return target

    print("⬇️  Downloading latest Lavalink release...")
    url, name = get_latest_lavalink_url()
    resp = requests.get(url, stream=True, timeout=30)
    resp.raise_for_status()

    with open(target, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)

    print("✅ Download complete:", target)
    return target

def run_lavalink(jar_path):
    """Launch Lavalink and keep a handle to terminate on exit."""
    if not jar_path.exists():
        raise FileNotFoundError(f"{jar_path} not found")
    print("🚀 Starting Lavalink...")

    process = subprocess.Popen(
        ["java", "-jar", str(jar_path.resolve())],
        cwd=jar_path.parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    def shutdown_handler(signum, frame):
        print("\n🛑 Stopping Lavalink...")
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    try:
        for line in process.stdout:
            print(line.decode(errors="ignore"), end="")
    except KeyboardInterrupt:
        shutdown_handler(None, None)

def check_java(min_version=17):
    """Check if Java is installed and is at least min_version."""
    try:
        result = subprocess.run(
            ["java", "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError:
        print("❌ Java not found! Please install Java 17+ and add it to PATH.")
        sys.exit(1)

    # Java prints version info to stderr
    version_line = result.stderr.strip().splitlines()[0]
    print(f"🔍 Detected Java: {version_line}")

    # Extract version number (works for OpenJDK 17+, 18+, etc.)
    import re
    match = re.search(r'version "(?P<ver>\d+)(\.(\d+))?', version_line)
    if not match:
        print("❌ Could not parse Java version.")
        sys.exit(1)

    major_version = int(match.group("ver"))
    if major_version < min_version:
        print(f"❌ Java version {major_version} detected, but Lavalink requires {min_version}+.")
        print("Please install a newer Java version and make sure it's in your PATH.")
        sys.exit(1)

    print(f"✅ Java version {major_version} is sufficient.")

if __name__ == "__main__":
    check_java()
    try:
        jar = ensure_lavalink()
        run_lavalink(jar)
    except Exception as e:
        print("❌ Error:", e)
