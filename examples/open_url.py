# Open a URL in a new tab. Override with: $env:URL = "https://example.com"
import os

url = os.environ.get("URL", "https://example.com")
tid = new_tab(url)
switch_tab(tid)
cdp("Target.activateTarget", targetId=tid)
wait_for_load()
print(page_info())
