import os
import sqlite3
import threading

DB_PATH = os.path.join(os.path.expanduser("~"), ".misha", "workspace_index.db")
IGNORE_DIRS = {".git", "node_modules", "venv", "__pycache__", ".misha", ".gemini", "build", "dist"}

class WorkspaceIndex:
    def __init__(self):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self._init_db()
        self.current_workspace = None

    def _init_db(self):
        # Create a regular table to store metadata
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filepath TEXT UNIQUE,
                mtime REAL
            )
        """)
        # Create FTS5 virtual table for full-text search
        self.conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS file_content USING fts5(
                filepath, 
                content
            )
        """)
        self.conn.commit()

    def set_workspace(self, path: str):
        self.current_workspace = path
        # Run indexing in background
        threading.Thread(target=self._index_workspace, args=(path,), daemon=True).start()

    def _index_workspace(self, path: str):
        print(f"[Workspace] Indexing {path}...")
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            for file in files:
                if file.startswith('.'): continue
                filepath = os.path.join(root, file)
                self._index_file(filepath)
        print("[Workspace] Indexing complete.")

    def _index_file(self, filepath: str):
        try:
            mtime = os.path.getmtime(filepath)
            cursor = self.conn.cursor()
            cursor.execute("SELECT mtime FROM files WHERE filepath = ?", (filepath,))
            row = cursor.fetchone()
            
            if row and row[0] == mtime:
                return # Already up to date

            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            if row:
                # Update
                cursor.execute("UPDATE files SET mtime = ? WHERE filepath = ?", (mtime, filepath))
                cursor.execute("UPDATE file_content SET content = ? WHERE filepath = ?", (content, filepath))
            else:
                # Insert
                cursor.execute("INSERT INTO files (filepath, mtime) VALUES (?, ?)", (filepath, mtime))
                cursor.execute("INSERT INTO file_content (filepath, content) VALUES (?, ?)", (filepath, content))
            
            self.conn.commit()
        except UnicodeDecodeError:
            pass # Skip binary files
        except Exception as e:
            pass # Silently skip errors

    def search(self, query: str, limit: int = 10):
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT filepath, snippet(file_content, 1, '<b>', '</b>', '...', 10) 
            FROM file_content 
            WHERE file_content MATCH ? 
            ORDER BY rank 
            LIMIT ?
        """, (query, limit))
        return cursor.fetchall()

workspace_index = WorkspaceIndex()
