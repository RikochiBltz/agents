"""
OpenAI-compatible tool definitions and dispatcher.
The LLM calls these; the agent executes them against the backend.
"""
from __future__ import annotations
import json
from typing import Any

# ── Shared filter item schema ─────────────────────────────────────────
_FILTER_ITEM = {
    "type": "object",
    "properties": {
        "column": {"type": "string"},
        "operator": {
            "type": "string",
            "enum": [
                "eq", "neq", "gt", "gte", "lt", "lte",
                "like", "notLike", "in", "notIn",
                "between", "isNull", "isNotNull",
                "startsWith", "endsWith", "contains",
            ],
            "description": (
                "eq/neq: equality. gt/gte/lt/lte: numeric or date comparison. "
                "like/notLike: SQL LIKE pattern (use % wildcard). "
                "startsWith/endsWith/contains: string matching without wildcards. "
                "in: value must be a JSON array. notIn: exclude these values. "
                "between: value must be [min, max] array. "
                "isNull/isNotNull: no value needed."
            ),
        },
        "value": {},
    },
    "required": ["column", "operator"],
}

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
                        "items": _FILTER_ITEM,
                    },
                    "sort": {
                        "type": "object",
                        "properties": {
                            "column":    {"type": "string"},
                            "direction": {"type": "string", "enum": ["asc", "desc"]},
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
                "Compute aggregated metrics via GROUP BY + SUM/COUNT/AVG/MIN/MAX. "
                "Use for totals, averages, rankings, counts, period breakdowns, and any summary. "
                "Supports computed grouping by date parts (YEAR, MONTH, WEEK, DAY, QUARTER, DATE), "
                "DISTINCT aggregates, post-aggregation HAVING filters, and multi-column sorting. "
                "At least one of groupBy or groupByExpressions is required."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {"type": "string"},
                    "groupBy": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Plain column names to group by. "
                            "Example: [\"dlg\", \"zone\"]. "
                            "At least one of groupBy or groupByExpressions is required."
                        ),
                    },
                    "groupByExpressions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "column": {
                                    "type": "string",
                                    "description": "Raw column name (e.g. 'date').",
                                },
                                "function": {
                                    "type": "string",
                                    "enum": ["YEAR", "MONTH", "WEEK", "DAY", "QUARTER", "DATE"],
                                    "description": "Date extraction function.",
                                },
                                "alias": {
                                    "type": "string",
                                    "description": "Output column name (e.g. 'annee', 'mois').",
                                },
                            },
                            "required": ["column", "function", "alias"],
                        },
                        "description": (
                            "Computed GROUP BY expressions using date functions. "
                            "Use to group by YEAR, MONTH, WEEK, DAY, QUARTER, or DATE of a column. "
                            "Example: [{\"column\":\"date\",\"function\":\"YEAR\",\"alias\":\"annee\"},"
                            "{\"column\":\"date\",\"function\":\"MONTH\",\"alias\":\"mois\"}] "
                            "→ SELECT YEAR(date) AS annee, MONTH(date) AS mois, ... GROUP BY YEAR(date), MONTH(date)."
                        ),
                    },
                    "metrics": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "column": {
                                    "type": "string",
                                    "description": "Column to aggregate. Use \"*\" only with COUNT.",
                                },
                                "function": {
                                    "type": "string",
                                    "enum": ["SUM", "COUNT", "AVG", "MIN", "MAX"],
                                },
                                "alias": {
                                    "type": "string",
                                    "description": "Output column name for this metric.",
                                },
                                "distinct": {
                                    "type": "boolean",
                                    "description": (
                                        "When true: COUNT(DISTINCT col) or SUM(DISTINCT col). "
                                        "Cannot be combined with COUNT(*)."
                                    ),
                                    "default": False,
                                },
                            },
                            "required": ["column", "function", "alias"],
                        },
                        "description": "Aggregate metrics to compute. At least one required.",
                    },
                    "filters": {
                        "type": "array",
                        "items": _FILTER_ITEM,
                        "description": "Pre-aggregation filters (WHERE). Applied before grouping.",
                    },
                    "having": {
                        "type": "array",
                        "items": _FILTER_ITEM,
                        "description": (
                            "Post-aggregation filters (HAVING). Applied after grouping. "
                            "Reference metric aliases or groupBy column names. "
                            "Example: [{\"column\":\"total_ttc\",\"operator\":\"gte\",\"value\":50000}]."
                        ),
                    },
                    "sorts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "column":    {"type": "string"},
                                "direction": {"type": "string", "enum": ["asc", "desc"]},
                            },
                            "required": ["column", "direction"],
                        },
                        "description": (
                            "Multi-column sort. Each column must be a groupBy column, "
                            "computed alias, or metric alias. Overrides the sort field."
                        ),
                    },
                    "sort": {
                        "type": "object",
                        "properties": {
                            "column":    {"type": "string"},
                            "direction": {"type": "string", "enum": ["asc", "desc"]},
                        },
                        "required": ["column", "direction"],
                        "description": "Single-column sort. Use sorts[] for multi-column ordering.",
                    },
                    "page": {"type": "integer", "default": 0},
                    "size": {"type": "integer", "default": 50, "maximum": 500},
                },
                "required": ["table", "metrics"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_periods",
            "description": (
                "Compare two time periods side-by-side with the same aggregation. "
                "Use for growth rate, year-over-year, or any 'X vs Y' comparison. "
                "Returns one row per group with metric values from both periods and a growth % column. "
                "Example: CA 2023 vs 2024 by delegate → one row per dlg with ca_2023, ca_2024, ca_growth_pct."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {"type": "string"},
                    "date_column": {
                        "type": "string",
                        "description": "Name of the date column to filter on (e.g. 'date').",
                    },
                    "period_a": {
                        "type": "object",
                        "properties": {
                            "label":      {"type": "string", "description": "Column suffix for period A (e.g. '2023')."},
                            "date_start": {"type": "string", "description": "Start date YYYY-MM-DD."},
                            "date_end":   {"type": "string", "description": "End date YYYY-MM-DD."},
                        },
                        "required": ["label", "date_start", "date_end"],
                    },
                    "period_b": {
                        "type": "object",
                        "properties": {
                            "label":      {"type": "string", "description": "Column suffix for period B (e.g. '2024')."},
                            "date_start": {"type": "string", "description": "Start date YYYY-MM-DD."},
                            "date_end":   {"type": "string", "description": "End date YYYY-MM-DD."},
                        },
                        "required": ["label", "date_start", "date_end"],
                    },
                    "groupBy": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Dimension columns to group by (e.g. ['dlg'], ['zone'], ['fam']).",
                    },
                    "metrics": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "column":   {"type": "string"},
                                "function": {"type": "string", "enum": ["SUM", "COUNT", "AVG", "MIN", "MAX"]},
                                "alias":    {"type": "string", "description": "Base alias — suffixed with _{label} in output."},
                            },
                            "required": ["column", "function", "alias"],
                        },
                    },
                    "extra_filters": {
                        "type": "array",
                        "items": _FILTER_ITEM,
                        "description": "Additional filters applied to both periods (not the date filters).",
                    },
                    "sort_by":  {"type": "string",  "description": "Column to sort the merged result by."},
                    "sort_dir": {"type": "string",  "enum": ["asc", "desc"], "default": "desc"},
                    "size":     {"type": "integer", "default": 50, "maximum": 500},
                },
                "required": ["table", "date_column", "period_a", "period_b", "groupBy", "metrics"],
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
