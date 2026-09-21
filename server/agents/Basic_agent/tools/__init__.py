"""Tools package initialization - exports all available tools."""

from .search import web_search
from .json_handler import save_to_json
from .pdf_handler import export_to_pdf
from .weather import get_weather

# List of all tools available for the agent
tools_list = [web_search, save_to_json, export_to_pdf, get_weather]

__all__ = ["web_search", "save_to_json", "export_to_pdf", "get_weather", "tools_list"]
