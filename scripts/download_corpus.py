#!/usr/bin/env python3
"""Download the small optional demo corpus; metadata and licenses stay in data/corpus.json."""
import json, pathlib, time, urllib.parse, urllib.request

root = pathlib.Path(__file__).parents[1]
manifest_path = root / "data/corpus.json"
manifest = json.loads(manifest_path.read_text()); items = manifest["images"]
out = root / "data/images"; out.mkdir(parents=True, exist_ok=True)
for item in items:
    target = out / f"{item['id']}.jpg"
    if item["id"] == "uncertain-01":
        source = next(x for x in items if x["id"] == "fox-01")
        item["source_url"], item["license"] = source["source_url"], source["license"]
        target.write_bytes((out / "fox-01.jpg").read_bytes())
        print(target)
        continue
    if target.exists() and "wikimedia.org" in item.get("source_url", ""):
        continue
    query = urllib.parse.urlencode({"action":"query", "generator":"search", "gsrsearch":f"{item['subject']} filetype:bitmap", "gsrnamespace":"6", "gsrlimit":"1", "prop":"imageinfo", "iiprop":"url|extmetadata", "iiurlwidth":"640", "format":"json"})
    request = urllib.request.Request("https://commons.wikimedia.org/w/api.php?" + query, headers={"User-Agent": "FlyRankCapstone/1.0 (image-matching demo)"})
    for attempt in range(4):
        try:
            result = json.load(urllib.request.urlopen(request)); break
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == 3: raise
            time.sleep(2 ** attempt)
    page = next(iter(result.get("query", {}).get("pages", {}).values()), None)
    if not page: raise RuntimeError(f"No Wikimedia image found for {item['subject']}")
    info = page["imageinfo"][0]; item["source_url"] = info.get("thumburl", info["url"]); item["license"] = "Wikimedia Commons; see source page"
    download = urllib.request.Request(item["source_url"], headers={"User-Agent": "FlyRankCapstone/1.0 (image-matching demo)"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(download) as response, target.open("wb") as output: output.write(response.read())
            break
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == 3: raise
            time.sleep(2 ** attempt)
    print(target)
manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
