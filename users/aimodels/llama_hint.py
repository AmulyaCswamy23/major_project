# users/aimodels/llama_hint.py
import os
import requests
from dotenv import load_dotenv

# Load your .env file (must contain HF_TOKEN)
load_dotenv()

API_URL = "https://api-inference.huggingface.co/models/meta-llama/Llama-3.1-8B-Instruct"
HEADERS = {"Authorization": f"Bearer {os.getenv('HUGGINGFACE_TOKEN')}"}

def generate_hint(prompt: str):
    """Send a prompt to Hugging Face LLaMA model and get back a hint."""
    payload = {
        "inputs": f"Give a concise hint for this question: {prompt}",
        "parameters": {
            "max_new_tokens": 80,
            "temperature": 0.6,
        },
    }

    response = requests.post(API_URL, headers=HEADERS, json=payload)
    
    if response.status_code != 200:
        raise Exception(f"💡 Error {response.status_code}: {response.text}")

    data = response.json()
    if isinstance(data, list) and "generated_text" in data[0]:
        return data[0]["generated_text"]
    elif isinstance(data, dict) and "error" in data:
        raise Exception(data["error"])
    else:
        return "No hint generated. Try again."