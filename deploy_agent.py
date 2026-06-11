import os
import subprocess
import sys

def deploy():
    print("=" * 60)
    print("Agent Sentinel — Deploying AidAssist to Agent Engine")
    print("=" * 60)

    # Set parameters
    project_id = "agent-sentinel-498916"
    region = "us-central1" # Or us-west1
    display_name = "AidAssist"
    
    # Path to agent folder
    agent_dir = os.path.join(os.path.dirname(__file__), "agent")
    
    # Run the adk deploy command
    cmd = [
        "adk", "deploy", "agent_engine",
        "--project", project_id,
        "--region", region,
        "--display_name", display_name,
        agent_dir
    ]
    
    print(f"Executing: {' '.join(cmd)}")
    
    try:
        # Use shell=True for pyenv shims on Windows
        result = subprocess.run(cmd, shell=True, check=True, text=True)
        print("=" * 60)
        print("Deployment succeeded!")
        print("=" * 60)
    except subprocess.CalledProcessError as e:
        print(f"Error during deployment: {e}")
        sys.exit(1)

if __name__ == "__main__":
    deploy()