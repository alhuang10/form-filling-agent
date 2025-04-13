import sys
import json
import openai
import logging
from playwright.sync_api import sync_playwright
import google.generativeai as genai
import os

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
DATA_PATH = "mock_data.json"

# ---------------- Initialization ---------------- #
def load_mock_data(path):
    with open(path, "r") as f:
        logging.info("Loaded mock data.")
        return json.load(f)

def configure_genai():
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        logging.error("Missing GOOGLE_API_KEY in environment.")
        sys.exit(1)
    genai.configure(api_key=api_key)

def get_target_url():
    if len(sys.argv) < 2:
        logging.error("Usage: python form_filler.py <URL>")
        sys.exit(1)
    url = sys.argv[1]
    logging.info(f"Target form URL: {url}")
    return url

def extract_rich_fields(page):
    logging.info("Extracting form field metadata...")
    fields = []
    elements = page.query_selector_all("input, select, textarea")
    for el in elements:
        field_data = {
            "tag": el.evaluate("e => e.tagName"),
            "type": el.get_attribute("type"),
            "id": el.get_attribute("id"),
            "name": el.get_attribute("name"),
            "placeholder": el.get_attribute("placeholder"),
            "aria_label": el.get_attribute("aria-label"),
            "label_text": None
        }

        # Try to find associated <label>
        label = None
        label = None
        if field_data["id"]:
            label_el = page.query_selector(f"label[for='{field_data['id']}']")
            if label_el:
                label = label_el.inner_text()
        if not label:
            parent_label_handle = el.evaluate_handle("e => e.closest('label')")
            if parent_label_handle:
                try:
                    label = parent_label_handle.evaluate("e => e.innerText")
                except Exception as e:
                     pass  # quietly skip if label can't be extracted

        field_data["label_text"] = label
        fields.append(field_data)

    logging.info(f"Found {len(fields)} fields with rich metadata.")
    return fields

def generate_prompt(field_info, user_data):
    return f"""
You are an expert web automation agent.

You will be given:
1. Structured metadata for all form fields on a webpage
2. Structured user data for one more people (e.g. attorney, client) and additional info

Your job is to match the user data fields to the correct form fields using label semantics and generate Python Playwright code to fill in the form.

### Form Field Metadata (JSON)
Each field contains:
- tag: e.g., INPUT, TEXTAREA, SELECT
- type: e.g., text, checkbox, tel, email
- id: the HTML id (to be used in the selector as #id)
- name: the HTML name (optional)
- label_text: visible label text that helps understand what the field is for

### User Data (JSON)
This is structured data with keys like 'family_name', 'email', 'zip_code', etc.

### Instructions:
- For each user data value that has a clear match to a form field label, generate the appropriate Playwright command.
- Make sure to look at fields containing "additional_info".
- Use:
    - `page.fill('#id', 'value')` for text/email/tel inputs or textareas
    - `page.check('#id')` for checkboxes when the value is True/yes/'Y'
    - `page.select_option('#id', 'value')` for dropdowns
- If a checkbox should not be checked (False/no/'N'), ignore it
- If a label or field doesn't clearly match any user data field, ignore it
- Do not fill any fields that require or represent a signature, including signature dates or attestations by an attorney, student, or organization representative.
- Do not generate comments or explanation, only return Python code lines.

Here is the field metadata:
{json.dumps(field_info, indent=2)}

Here is the person data:
{json.dumps(user_data, indent=2)}
"""
    
def ask_gemini_to_map_fields(field_info, user_data) -> str:
    logging.info("Sending field info and user data to Gemini Flash 2.0...")
    model = genai.GenerativeModel("gemini-2.0-flash")
    prompt = generate_prompt(field_info, user_data)
    response = model.generate_content(prompt)
    logging.info("Received code instructions from Gemini.")
    code = response.text.replace("```python", "").replace("```", "")
    return code

def fill_form(url, mock_data):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        logging.info("Navigating to the target URL...")
        page.goto(url)

        field_info = extract_rich_fields(page)
        agent_generated_code = ask_gemini_to_map_fields(field_info, mock_data)
        
        logging.info("Executing generated code...")
        try:
            exec(agent_generated_code, {"page": page})
        except Exception as e:
            logging.error(f"Error executing agent generated code: {e}")

        logging.info("Waiting to view the filled form before closing...")
        page.wait_for_timeout(1000000)
        browser.close()

def main():
    configure_genai()
    mock_data = load_mock_data(DATA_PATH)
    url = get_target_url()
    fill_form(url, mock_data)
    

if __name__ == "__main__":
    main()
