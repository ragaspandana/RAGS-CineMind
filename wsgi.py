"""Entry point for production servers (gunicorn / PythonAnywhere).

    gunicorn wsgi:app
"""
from app import create_app

app = create_app()
