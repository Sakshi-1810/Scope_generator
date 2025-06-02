import pymysql

def get_mysql_connection():
    return pymysql.connect(
        host="localhost",
        user="root",
        password="",  
        database="rag_scope_db"
    )
