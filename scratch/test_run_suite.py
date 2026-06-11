import requests
import json

def test_suite():
    url = "http://localhost:8000/tools/run-test-suite"
    payload = {
        "target_agent_id": "hr_assistant",
        "attack_vector": "all"
    }
    headers = {"Content-Type": "application/json"}
    
    print("Sending POST request to /tools/run-test-suite...")
    try:
        response = requests.post(url, data=json.dumps(payload), headers=headers, stream=True)
        print("Status code:", response.status_code)
        for line in response.iter_lines():
            if line:
                decoded_line = line.decode('utf-8')
                print("Stream line:", decoded_line)
                # Parse to see if it completed or failed
                try:
                    data = json.loads(decoded_line)
                    if data.get("status") == "error":
                        print("Error message:", data.get("message"))
                except Exception:
                    pass
    except Exception as e:
        print("Failed to call endpoint:", e)

if __name__ == "__main__":
    test_suite()
