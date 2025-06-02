import os
import fitz  
import pickle
import faiss
import pymysql
import subprocess
import numpy as np
import re
import json
import pandas as pd 
from docx import Document
from sentence_transformers import SentenceTransformer
from langchain.text_splitter import RecursiveCharacterTextSplitter

DATA_DIR = "data"
VECTOR_STORE = "vector_store/index.faiss"
TEXTS_PICKLE = "vector_store/texts.pkl"

def get_mysql_connection():
    return pymysql.connect(
        host="localhost",
        user="root",
        password="",
        database="rag_scope_db",
        charset='utf8mb4',
        use_unicode=True
    )

def extract_text(file_path):
    text = ""
    if file_path.endswith(".pdf"):
        with fitz.open(file_path) as doc:
            for page in doc:
                text += page.get_text()
    elif file_path.endswith(".docx"):
        doc = Document(file_path)
        for para in doc.paragraphs:
            text += para.text + "\n"
    elif file_path.endswith(".txt"):
        with open(file_path, 'r', encoding='utf-8') as f:
            text = f.read()
    return text

def chunk_text(text):
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    return splitter.split_text(text)

model = SentenceTransformer("BAAI/bge-small-en")

def embed_chunks(chunks):
    return model.encode(chunks, normalize_embeddings=True)

def store_chunks_mysql(file_name, chunks):
    conn = get_mysql_connection()
    cursor = conn.cursor()
    for i, chunk in enumerate(chunks):
        chunk = chunk.encode('utf-8', 'ignore').decode('utf-8').strip()
        cursor.execute("""
            INSERT INTO document_chunks (file_name, page_number, chunk_text)
            VALUES (%s, %s, %s)
        """, (file_name, i + 1, chunk))
    conn.commit()
    conn.close()

def save_faiss_index(vectors, chunks):
    os.makedirs(os.path.dirname(VECTOR_STORE), exist_ok=True)
    dim = vectors.shape[1]
    index = faiss.IndexFlatL2(dim)
    index.add(np.array(vectors))
    faiss.write_index(index, VECTOR_STORE)
    with open(TEXTS_PICKLE, 'wb') as f:
        pickle.dump(chunks, f)

def store_sample_scope(name, table_json):
    conn = get_mysql_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO sample_scope_examples (example_name, scope_table) VALUES (%s, %s)",
        (name, table_json)
    )
    conn.commit()
    conn.close()

def generate_scope_table(query, context_chunks):
    context = "\n\n".join(context_chunks)

    prompt = f"""
You are a product lead at a software company. You are planning the full development of a Mobile App for a client. Below is the complete requirement document extracted from the client.

Your task is to analyze the requirements and generate a comprehensive **Scope of Work**, structured in a valid JSON format.

---

### OBJECTIVE:
Break down all functional and non-functional tasks into **logical modules**. For each module, identify at least **3 sub-modules or features** that represent user-facing functionality or system-level responsibilities.

Think holistically — cover areas like user interaction, content management, admin tools, reporting, notifications, integrations, and security.

---

### OUTPUT:
You MUST return a valid, properly formatted JSON object with a "scope_of_work" key, which contains an array of modules.

Each module must contain:
- "module": Name of the distinct functional category (e.g., User Management, security)
- "sub_modules": An array of 2–4 sub-features with:
    - "sub_module": Name of the feature
    - "description": Clear user-oriented explanation

Return 8–10 unique functional modules, each with 2–4 sub-modules.

IMPORTANT: DO NOT use escaped underscores or backslashes in your JSON. Make sure all commas are correctly placed and there are no trailing commas. The JSON must be valid and parse correctly with json.loads().
You MUST include the outer "scope_of_work" key containing the array. Do not return just the array without this wrapper object.
---

### CONTEXT:
{context}

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

Return ONLY the JSON - no additional text, no markdown code blocks. The JSON must be valid and correctly formatted.
"""

    result = subprocess.run(
        ["ollama", "run", "llama3.1"],
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8"
    )

    response_text = result.stdout.strip()

    try:
        if "```json" in response_text and "```" in response_text[response_text.find("```json") + 7:]:
            start = response_text.find("```json") + 7
            end = response_text.find("```", start)
            json_str = response_text[start:end].strip()
            return json.loads(json_str)
        
        if "```" in response_text:
            start = response_text.find("```") + 3
            end = response_text.find("```", start)
            if end != -1:
                json_str = response_text[start:end].strip()
                return json.loads(json_str)
        
        json_pattern = r'\{[\s\S]*\}'
        match = re.search(json_pattern, response_text)
        if match:
            json_str = match.group(0)
            return json.loads(json_str)
            
        print("Could not extract valid JSON from response")
        return {"scope_of_work": []}
        
    except json.JSONDecodeError as e:
        print("❌ JSON decode error:", e)
        print("⚠️ Raw output looked like:\n", response_text)
        return {"scope_of_work": []}

def process_and_generate(file_path, user_query):
    print("\nExtracting text from document...")
    text = extract_text(file_path)

    print("Chunking document...")
    chunks = chunk_text(text)

    print("Embedding chunks...")
    vectors = embed_chunks(chunks)

    print("Storing chunks in MySQL...")
    try:
        store_chunks_mysql(os.path.basename(file_path), chunks)
    except Exception as e:
        print(f"MySQL storage error: {e}")
        print("Continuing without MySQL storage...")

    print("Saving vectors to FAISS index...")
    save_faiss_index(vectors, chunks)

    print("Retrieving relevant chunks for query...")
    relevant_chunks = chunks

    print("Generating scope table with llama (JSON format)...")
    table_json = generate_scope_table(user_query, relevant_chunks)

    with open("scope_output.json", "w") as f:
        json.dump(table_json, f, indent=2)
        
    return table_json

def json_to_dataframes(json_data):
    try:
        # Handle different input types
        if isinstance(json_data, dict):
            data = json_data
        else:
            data = json.loads(json_data)
        
        # Handle cases where the model returns an array directly
        if isinstance(data, list):
            scope_list = data
        else:
            # Use the normal approach of looking for scope_of_work key
            scope_list = data.get("scope_of_work", [])
        
        if not scope_list:
            print("No scope of work data found!")
            df_scope = pd.DataFrame(columns=["Module", "Sub-Module", "Description"])
            return df_scope, "scope_of_work.xlsx", None
        
        flattened_rows = []
        for module in scope_list:
            module_name = module.get("module", "")
            for sub_module in module.get("sub_modules", []):
                flattened_rows.append({
                    "Module": module_name,
                    "Sub-Module": sub_module.get("sub_module", ""),
                    "Description": sub_module.get("description", "")
                })
        
        df_scope = pd.DataFrame(flattened_rows)

        print("\n Scope of Work:")
        print(df_scope)

        excel_file = "scope_of_work.xlsx"
        df_scope.to_excel(excel_file, index=False)

        print(f"✅ Excel file saved as: {excel_file}")
        return df_scope, excel_file, None

    except Exception as e:
        print("❌ Failed to convert data to DataFrame:", e)
        print(f"Error details: {str(e)}")
        return None, None, None
    
if __name__ == "__main__":
    FILE = r"C:\Users\Owner\Desktop\Webanix\rag_scope_project\data\HR Payroll System Requirements.docx"
    QUERY = "Generate a structured Scope of Work in JSON for developing a mobile app based on the attached document. Group by module, and describe each feature clearly."

    table_json = process_and_generate(FILE, QUERY)

    print("\n== FINAL JSON OUTPUT ==\n")
    print(json.dumps(table_json, indent=2))

    df_scope, _, _ = json_to_dataframes(table_json)