import os
from google.cloud import dialogflowcx_v3

def list_agents(project_id, location):
    print(f"\n--- Listing agents in location: {location} ---")
    client_options = None
    if location != 'global':
        api_endpoint = f"{location}-dialogflow.googleapis.com:443"
        client_options = {"api_endpoint": api_endpoint}
        
    client = dialogflowcx_v3.AgentsClient(client_options=client_options)
    parent = f"projects/{project_id}/locations/{location}"
    
    try:
        response = client.list_agents(parent=parent)
        count = 0
        for agent in response:
            count += 1
            print(f"- Display Name: {agent.display_name}")
            print(f"  Name/ID: {agent.name}")
        if count == 0:
            print("No agents found in this location.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "agent-sentinel-498916")
    
    # Try all common Dialogflow CX locations
    locations = ["us-central1", "global", "us", "europe", "europe-west1"]
    for loc in locations:
        list_agents(project_id, loc)
