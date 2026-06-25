import sys
import mido
import time
import json
import xml.etree.ElementTree as ET
import os
from google import genai
from google.genai import types
from dotenv import load_dotenv

# 1. Initialize the GenAI Client
# WARNING: Keep your API key secret!
load_dotenv() # Load environment variables from .env file
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# 2. DYNAMIC CONFIGURATION LOADER
def load_midi_map_from_xml(xml_path):
    """
    Parses the Neural DSP XML configuration file directly 
    and builds the hardware abstraction layer dynamically.
    """
    dynamic_map = {}
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        
        for routing in root.findall('.//routing'):
            target = routing.get('target')
            cc_number = int(routing.get('data1'))
            enabled = routing.get('enabled')
            
            if enabled == "1" and target:
                dynamic_map[target] = {
                    "cc": cc_number,
                    "label": target.replace("Amp", " Amp ")
                }
                
        print(f"[System] Successfully loaded {len(dynamic_map)} parameters from {xml_path}")
        return dynamic_map
        
    except FileNotFoundError:
        print(f"[Error] Configuration file not found at: {xml_path}")
        return {}
    except Exception as e:
        print(f"[Error] Failed to parse XML file: {e}")
        return {}

# 3. THE DYNAMIC AI TRANSLATOR ENGINE (With Exponential Backoff)
def get_gemini_tone_preset(user_prompt, midi_map, max_retries=3):
    print(f"\n[Gemini Engine] Analyzing request: '{user_prompt}'...")
    
    valid_keys = list(midi_map.keys())
    
    system_instruction = f"""
    You are an expert audio engineer specializing in Neural DSP plugins. 
    Translate the user's guitar tone request into specific knob values.
    
    Output ONLY a JSON object. No markdown, no explanations.
    The keys must exactly match a subset of these available parameters found in the plugin configuration:
    {json.dumps(valid_keys)}
    
    The values must be integers representing percentages from 0 to 100.
    Example: {{"cleanAmpVolume": 45, "cleanAmpBass": 60, "cleanAmpMaster": 80}}
    """

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        temperature=0.7
    )

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=user_prompt,
                config=config
            )
            return json.loads(response.text)
            
        except Exception as e:
            error_message = str(e)
            if "503" in error_message or "UNAVAILABLE" in error_message:
                wait_time = 2 ** attempt
                print(f"[Warning] API busy. Retrying in {wait_time}s... (Attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
            else:
                print(f"[Error] Gemini Engine failed: {error_message}")
                return None
                
    print("[Error] Max retries reached. The AI server is too busy right now.")
    return None

# 4. THE MIDI INJECTOR
def apply_preset(preset_data, midi_map, port_name='loopMIDI Port 0'):
    if not preset_data:
        print("[System] No preset data to apply.")
        return
        
    try:
        with mido.open_output(port_name) as port:
            print("\n[System] Injecting Tone Configuration...")
            for param, percentage_value in preset_data.items():
                if param in midi_map:
                    cc_num = midi_map[param]["cc"]
                    label = midi_map[param]["label"]
                    
                    # Convert AI percentage (0-100) to MIDI byte (0-127)
                    midi_value = int((percentage_value / 100.0) * 127)
                    midi_value = max(0, min(127, midi_value))
                    
                    msg = mido.Message('control_change', control=cc_num, value=midi_value)
                    port.send(msg)
                    
                    print(f" -> {label}: {percentage_value}% (CC {cc_num} -> Value {midi_value})")
                    time.sleep(0.05)
            print("[System] Injection Complete!\n")
    except Exception as e:
        print(f"[Error] MIDI Transmission failed: {e}")

# --- EXECUTION ---
if __name__ == "__main__":
    print("=======================================================")
    print("   NeuralAutomator CLI v1.1 (Powered by Gemini 2.5)   ")
    print("=======================================================")
    
    CONFIG_PATH = "midi-mapping.xml" 
    MIDI_MAP = load_midi_map_from_xml(CONFIG_PATH)
    
    if not MIDI_MAP:
        print("[Fatal] Could not initialize MIDI map. Exiting script.")
        sys.exit(1)

    # METHOD 1: One-Shot Terminal Command
    # E.g., running: py main.py "Give me a crunchy tone"
    if len(sys.argv) > 1:
        user_request = " ".join(sys.argv[1:])
        ai_preset = get_gemini_tone_preset(user_request, MIDI_MAP)
        apply_preset(ai_preset, MIDI_MAP)
        print("\nTask complete. Exiting.")
        sys.exit(0)
        
    # METHOD 2: Interactive Runtime Loop
    # E.g., running: py main.py
    print("\nSystem ready! Describe the tone you want below.")
    print("Type 'exit' or 'quit' to close the application.\n")
    
    while True:
        try:
            # Capture dynamic input from the terminal
            user_request = input("Enter tone request > ").strip()
            
            # Check for termination commands
            if user_request.lower() in ['exit', 'quit', 'q']:
                print("\nShutting down NeuralAutomator. Happy playing!")
                break
                
            # Skip empty entries
            if not user_request:
                continue
                
            # Run the generation pipeline
            ai_preset = get_gemini_tone_preset(user_request, MIDI_MAP)
            apply_preset(ai_preset, MIDI_MAP)
            
        except KeyboardInterrupt:
            # Handles Ctrl+C gracefully without an ugly traceback error
            print("\n\nShutting down NeuralAutomator. Happy playing!")
            break
        except Exception as global_error:
            # Prevents unexpected errors from breaking the entire terminal session
            print(f"\n[Loop Error] An unexpected error occurred: {global_error}")
            print("Restarting prompt loop...\n")