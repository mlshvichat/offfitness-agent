import json, os, subprocess, urllib.request
url = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000"
req = urllib.request.Request(url, headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]})
with urllib.request.urlopen(req, timeout=45) as response:
    models = json.load(response)["models"]
available = {m["name"].removeprefix("models/") for m in models if "generateContent" in m.get("supportedGenerationMethods", [])}
candidates = [m for m in ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3-flash-preview"] if m in available]
print("Available models:", sorted(available), flush=True)
print("Available candidate models:", candidates, flush=True)
for model in candidates:
    print("Testing model:", model, flush=True)
    result = subprocess.run(["python", "agent.py"], env={**os.environ, "GEMINI_MODEL": model})
    if result.returncode == 0:
        print("VALIDATED_MODEL=" + model, flush=True)
        print(open("out/preview.txt", encoding="utf-8").read(), flush=True)
        break
    report = json.load(open("out/editorial-report.json"))
    print(json.dumps(report, ensure_ascii=False), flush=True)
else:
    raise SystemExit("No model produced an approved preview")
