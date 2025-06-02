import os
import fitz  
import pickle
import faiss
import pymysql
import subprocess
import numpy as np
from docx import Document
from sentence_transformers import SentenceTransformer
from langchain.text_splitter import RecursiveCharacterTextSplitter
import json
import pandas as pd 

DATA_DIR = "data"
VECTOR_STORE = "vector_store/index.faiss"
TEXTS_PICKLE = "vector_store/texts.pkl"


def get_mysql_connection():
    return pymysql.connect(
        host="localhost",
        user="root",
        password="",
        database="rag_scope_db"
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
        cursor.execute("""
            INSERT INTO document_chunks (file_name, page_number, chunk_text)
            VALUES (%s, %s, %s)
        """, (file_name, i + 1, chunk))
    conn.commit()
    conn.close()


def save_faiss_index(vectors, chunks):
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
You are a senior business analyst. Based on the project requirements and context, generate a detailed scope of work in valid JSON format.

The JSON must include the following three sections:

1. "scope_of_work" → A list of features grouped by functional modules.
   - Include at least 5 distinct modules
   - Each item must contain:
     - "module": the main functional area (e.g., "Attendance", "Payroll", "Recruitment", etc.)
     - "sub_module": the specific feature within that module
     - "description": a clear, non-redundant explanation of what the sub_module does

2. "team_planning" → A list of roles involved in the project.
   - Each item must contain:
     - "role"
     - "responsibility"
     - "allocation_hours"

3. "milestones" → Key delivery phases of the project.
   - Each item must contain:
     - "milestone"
     - "modules_covered"
     - "estimated_days"

### CONTEXT:
{context}

### FORMAT:
{{
  "scope_of_work": [
    {{
      "module": "string",
      "sub_module": "string",
      "description": "string"
    }}
  ],
  "team_planning": [
    {{
      "role": "string",
      "responsibility": "string",
      "allocation_hours": number
    }}
  ],
  "milestones": [
    {{
      "milestone": "string",
      "modules_covered": "string",
      "estimated_days": number
    }}
  ]
}}

Only return valid JSON. Do not add markdown or comments.
"""

    result = subprocess.run([
        "ollama", "run", "mistral"
    ], input=prompt, capture_output=True, text=True, encoding="utf-8")

    return result.stdout.strip()


def process_and_generate(file_path, user_query):
    print("\nExtracting text from document...")
    text = extract_text(file_path)

    print("Chunking document...")
    chunks = chunk_text(text)

    print("Embedding chunks...")
    vectors = embed_chunks(chunks)

    print("Storing chunks in MySQL...")
    store_chunks_mysql(os.path.basename(file_path), chunks)

    print("Saving vectors to FAISS index...")
    save_faiss_index(vectors, chunks)

    print("Retrieving relevant chunks for query...")
    relevant_chunks = chunk_text(text)  

    print("Generating scope table with Mistral (JSON format)...")
    table_json = generate_scope_table(user_query, relevant_chunks)

    return table_json  


def json_to_dataframes(json_str):
    try:
        data = json.loads(json_str)

        df_scope = pd.DataFrame(data.get("scope_of_work", []))
        df_team = pd.DataFrame(data.get("team_planning", []))
        df_milestones = pd.DataFrame(data.get("milestones", []))

        print("\n Scope of Work:")
        print(df_scope)

        print("\n Team Planning:")
        print(df_team)

        print("\n Milestones:")
        print(df_milestones)

        return df_scope, df_team, df_milestones

    except Exception as e:
        print("❌ Failed to convert JSON to DataFrames:", e)
        return None, None, None


if __name__ == "__main__":
    FILE = os.path.join(DATA_DIR, "HR Payroll System Requirements.docx")
    QUERY = "Generate project scope, team planning and milestones for a HR Payroll System"

    table_json = process_and_generate(FILE, QUERY)

    print("\n== FINAL JSON OUTPUT ==\n")
    print(table_json)

    with open("scope_output.json", "w") as f:
        f.write(table_json)

    df_scope, df_team, df_milestones = json_to_dataframes(table_json)
