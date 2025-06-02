import fitz  
import docx  
import os
import json
import google.generativeai as genai

API_KEY = "Your_api_key"
if not API_KEY:
    raise ValueError("Missing Google API Key! Ensure it is set correctly.")

genai.configure(api_key=API_KEY)

def extract_text_from_pdf(file_path):
    text = ""
    with fitz.open(file_path) as doc:
        for page in doc:
            text += page.get_text()
    return text

def extract_text_from_docx(file_path):
    doc = docx.Document(file_path)
    return "\n".join(para.text for para in doc.paragraphs)

def extract_text_from_txt(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()

def generate_scope_of_work(text):
    prompt_text = f"""
You are a product lead at a software company. You are planning the full development of a Mobile App for a client. Below is the complete requirement document extracted from the client.

Your task is to analyze the requirements and generate a comprehensive **Scope of Work**, structured in a valid JSON format.

---

### OBJECTIVE:
Break down all functional and non-functional tasks into **logical modules**. For each module, identify at least **3 or 4 sub-modules or features** that represent user-facing functionality or system-level responsibilities.

Think holistically — cover areas like user interaction, content management, admin tools, reporting, notifications, integrations, and security.
Elaborate each sub-module very clearly in terms of modules.
---

### OUTPUT:
You MUST return a valid, properly formatted JSON object with a "scope_of_work" key, which contains an array of modules.

Each module must contain:
- "module": Name of the distinct functional category (e.g., User Management, Security)
- "sub_modules": An array of 3–4 sub-features with:
    - "sub_module": Name of the feature
    - "description": Clear user-oriented explanation

Return all possible unique functional modules, each with atleast 3–4 sub-modules.

IMPORTANT: DO NOT use escaped underscores or backslashes in your JSON. Make sure all commas are correctly placed and there are no trailing commas. The JSON must be valid and parse correctly with json.loads().
You MUST include the outer "scope_of_work" key containing the array. Do not return just the array without this wrapper object.

---

### CONTEXT:
{text}

---

### FORMAT:
{{
  "scope_of_work": [
    {{
      "module": "string",
      "sub_modules": [
        {{
          "sub_module": "string",
          "description": "string"
        }}
      ]
    }}
  ]
}}
"""
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt_text, generation_config={"temperature": 0.0})
        raw_output = response.text.strip()

        cleaned_str = raw_output.strip("`").strip("json").strip()

        return json.loads(cleaned_str)

    except json.JSONDecodeError as e:
        print(f"❌ Failed to parse JSON: {e}")
        print("Response was:\n", raw_output)
        return {"scope_of_work": []}
    except Exception as e:
        print(f"❌ Error with API request: {e}")
        return {"scope_of_work": []}

import pandas as pd

def save_scope_json_to_csv(scope_json, output_path="scope_of_work.csv"):
    if not scope_json or "scope_of_work" not in scope_json:
        print("❌ Invalid or empty scope JSON.")
        return

    rows = []
    for module in scope_json["scope_of_work"]:
        module_name = module["module"]
        for sub in module["sub_modules"]:
            rows.append({
                "Module": module_name,
                "Sub Module": sub["sub_module"],
                "Description": sub["description"]
            })

    df = pd.DataFrame(rows)
    print(df)
    df.to_csv(output_path, index=False)
    print(f"✅ CSV file saved as: {output_path}")


def process_pipeline(file_path):
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        text = extract_text_from_pdf(file_path)
    elif ext == ".docx":
        text = extract_text_from_docx(file_path)
    elif ext == ".txt":
        text = extract_text_from_txt(file_path)
    else:
        raise ValueError("Unsupported file type")

    print(f"✅ Extracted text from {file_path}")
    result_json = generate_scope_of_work(text)

    print("\n✅ Final Output:\n")
    print(json.dumps(result_json, indent=2))

    save_scope_json_to_csv(result_json)


if __name__ == "__main__":
    FILE_PATH = r"C:\Users\Owner\Desktop\Webanix\rag_scope_project\data\HR Payroll System Requirements.docx"
    process_pipeline(FILE_PATH)
