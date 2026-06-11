import os
import google.generativeai as genai

def test_models():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("No GEMINI_API_KEY set.")
        return
    genai.configure(api_key=api_key)
    
    print("Listing models...")
    try:
        models = genai.list_models()
        for m in models:
            print(f"- Name: {m.name}, Supported Actions: {m.supported_generation_methods}")
    except Exception as e:
        print(f"Error listing models: {e}")

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    test_models()
