import sys
import json
import openai
import logging
from playwright.sync_api import sync_playwright
import google.generativeai as genai
import os

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# load data from mock_data.json
with open("mock_data.json", "r") as f:
    mock_data = json.load(f)
    logging.info("Loaded mock data.")

# Get URL from command line
if len(sys.argv) < 2:
    logging.error("Usage: python form_filler.py <URL>")
    sys.exit(1)

url = sys.argv[1]
logging.info(f"Target form URL: {url}")

genai.configure(api_key=os.environ["GOOGLE_API_KEY"])

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


def ask_gemini_to_map_fields(field_info, user_data):
    logging.info("Sending field info and user data to Gemini Flash 2.0...")

    prompt = f"""
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
- Do not generate comments or explanation, only return Python code lines.

Here is the field metadata:
{json.dumps(field_info, indent=2)}

Here is the person data:
{json.dumps(user_data, indent=2)}
"""

    model = genai.GenerativeModel("gemini-2.0-flash")
    response = model.generate_content(prompt)

    logging.info("Received instructions from Gemini.")
    return response.text


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        logging.info("Navigating to the target URL...")
        page.goto(url)

        field_info = extract_rich_fields(page)

        agent_generated_code = ask_gemini_to_map_fields(field_info, mock_data)
        
        # Gemini specific post processing (TODO: refactor)
        agent_generated_code = agent_generated_code.replace("```python", "")
        agent_generated_code = agent_generated_code.replace("```", "")

        # Save generated text to a file
        with open("agent_generated_code.txt", "w") as f:
            f.write(agent_generated_code)

        logging.info("Executing generated code...")
        try:
            exec(agent_generated_code, {"page": page})
        except Exception as e:
            logging.error(f"Error executing agent generated code: {e}")

        logging.info("Waiting to view the filled form before closing...")
        page.wait_for_timeout(1000000)
        browser.close()

if __name__ == "__main__":
    main()
