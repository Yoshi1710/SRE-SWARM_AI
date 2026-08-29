import urllib.request
import json

url = "http://127.0.0.1:8000/triage"
payload = {
    "language": "python",
    "broken_code": "def divide(a, b):\n    return a / b\nprint(divide(10, 0))",
    "error_log": "ZeroDivisionError: division by zero"
}

req = urllib.request.Request(
    url,
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"}
)

try:
    with urllib.request.urlopen(req) as response:
        result = json.loads(response.read().decode())
        print("\n--- SRE SWARM RESPONSE ---")
        print(json.dumps(result, indent=2))
except Exception as e:
    print(f"Error: {e}")