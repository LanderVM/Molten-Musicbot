import time
import requests
import os

url = f"http://{os.environ['LAVALINK_HOST']}:{os.environ['LAVALINK_PORT']}/v4/info"
headers = {"Authorization": os.environ['LAVALINK_PASSWORD']}

while True:
    try:
        r = requests.get(url, headers=headers, timeout=2)
        if r.status_code == 200:
            print("Lavalink is ready!")
            break
    except requests.RequestException:
        pass
    print("Waiting for Lavalink...")
    time.sleep(5)
