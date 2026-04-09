"""
OpenAI-compatible tool definitions and dispatcher.
The LLM calls these; the agent executes them against the backend.
"""
from __future__ import annotations
import json
from typing import Any

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_schema",
            "description": (
                "Search the schema for tables whose name or columns match a keyword. "
                "Use this FIRST when you are not sure which table to query. "
                "Returns table names, their module, and full column list."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": (
                            "Keyword to search in table names and column names. "
                            "Examples: 'year', 'zone', 'vente', 'stock', 'date', 'dlg'."
                        ),
                    }
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_table_columns",
            "description": (
                "Get the typed column list for a specific table. "
                "Call this before querying if you need to confirm exact column names and types."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {"type": "string", "description": "Exact table name."},
                },
                "required": ["table"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_modules",
            "description": "List all available data modules and the tables they contain.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tables",
            "description": "List all accessible table names, optionally filtered to one module.",
            "parameters": {
                "type": "object",
                "properties": {
                    "module": {
                        "type": "string",
                        "description": "Optional module name to filter by.",
                        "enum": [
                            "ANIMATION", "VENTES", "PRODUITS_STOCK", "DEMANDES",
                            "REFERENTIELS", "DOCUMENTS_ENQUETES", "MARKETING_PROMO",
                            "FINANCE", "ORGANISATION_TECHNIQUE",
                        ],
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_table",
            "description": (
                "Fetch filtered and sorted raw rows from a table. "
                "Use for detailed listings, row-level searches, or individual records. "
                "All filter conditions are combined with AND only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {"type": "string"},
                    "filters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "column":   {"type": "string"},
                                "operator": {
                                    "type": "string",
                                    "enum": ["eq","neq","gt","gte","lt","lte","like","in"],
                                },
                                "value": {},
                            },
                            "required": ["column", "operator", "value"],
                        },
                    },
                    "sort": {
                        "type": "object",
                        "properties": {
                            "column":    {"type": "string"},
                            "direction": {"type": "string", "enum": ["asc","desc"]},
                        },
                        "required": ["column", "direction"],
                    },
                    "page": {"type": "integer", "default": 0},
                    "size": {"type": "integer", "default": 50, "maximum": 500},
                },
                "required": ["table"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "aggregate_table",
            "description": (
                "Compute aggregated KPIs using GROUP BY + SUM/COUNT/AVG/MIN/MAX. "
                "Use for totals, averages, rankings, counts, and any summary question. "
                "IMPORTANT: groupBy only accepts plain column names — YEAR(), MONTH(), "
                "DATE_FORMAT() and other SQL functions are NOT supported. "
                "For year/month grouping use pre-computed tables instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {"type": "string"},
                    "groupBy": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Plain column names only. SQL functions not supported.",
                    },
                    "metrics": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "column":   {"type": "string", "description": "Column name or '*' for COUNT(*)"},
                                "function": {"type": "string", "enum": ["SUM","COUNT","AVG","MIN","MAX"]},
                                "alias":    {"type": "string"},
                            },
                            "required": ["column", "function", "alias"],
                        },
                    },
                    "filters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "column":   {"type": "string"},
                                "operator": {"type": "string", "enum": ["eq","neq","gt","gte","lt","lte","like","in"]},
                                "value":    {},
                            },
                            "required": ["column", "operator", "value"],
                        },
                    },
                    "sort": {
                        "type": "object",
                        "properties": {
                            "column":    {"type": "string"},
                            "direction": {"type": "string", "enum": ["asc","desc"]},
                        },
                        "required": ["column", "direction"],
                    },
                    "page": {"type": "integer", "default": 0},
                    "size": {"type": "integer", "default": 50, "maximum": 500},
                },
                "required": ["table", "groupBy", "metrics"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browse_table",
            "description": "Read a table without filters — preview content or explore sample values.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {"type": "string"},
                    "page":  {"type": "integer", "default": 0},
                    "size":  {"type": "integer", "default": 20, "maximum": 500},
                },
                "required": ["table"],
            },
        },
    },
]


def format_tool_result(result: Any) -> str:
    if isinstance(result, (dict, list)):
        return json.dumps(result, ensure_ascii=False, default=str)
    return str(result)
