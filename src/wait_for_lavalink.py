import os
import time

import requests


def wait_for_lavalink() -> None:
    scheme = "https" if os.getenv("SSL_ENABLED", "false").lower() == "true" else "http"
    url = f"{scheme}://{os.environ['LAVALINK_HOST']}:{os.environ['LAVALINK_PORT']}/v4/info"
    headers = {"Authorization": os.environ["LAVALINK_PASSWORD"]}
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            with requests.get(url, headers=headers, timeout=2) as response:
                if response.status_code == 200:
                    print("Lavalink is ready!")
                    return
                if response.status_code in (401, 403):
                    raise RuntimeError("Lavalink rejected the configured credentials")
        except requests.RequestException:
            pass
        print("Waiting for Lavalink...")
        time.sleep(5)
    raise RuntimeError("Lavalink did not become ready within 120 seconds")


if __name__ == "__main__":
    wait_for_lavalink()
