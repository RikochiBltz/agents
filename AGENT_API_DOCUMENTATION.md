# MediNote Backend — AI Agent API Documentation

## Overview

This backend exposes a role-aware data API designed for AI agents (DataAgent, Analysis Agent).
Every request must carry a valid JWT token. The backend enforces role-based access automatically —
the agent never needs to hard-code what a user can or cannot see.

Base URL (local): `http://localhost:8081`
Base URL (production): via API Gateway on port `8085`

---

## 1. Authentication

### 1.1 Login
The agent must first obtain a JWT by logging in with the user's credentials.

**Request**
```
POST /api/auth/login
Content-Type: application/json
```
```json
{
  "email": "user@example.com",
  "password": "userpassword"
}
```

**Response**
```json
{
  "accessToken": "eyJhbGciOiJIUzI1NiJ9...",
  "refreshToken": "d8f3a1...",
  "role": "DELEGATE"
}
```

### 1.2 Refresh Token
When the access token expires (15 minutes), use the refresh token to get a new one.

**Request**
```
POST /api/auth/refresh
Content-Type: application/json
```
```json
{
  "refreshToken": "d8f3a1..."
}
```

**Response**
```json
{
  "accessToken": "eyJhbGciOiJIUzI1NiJ9...",
  "refreshToken": "newrefreshtoken..."
}
```

### 1.3 Using the Token
All data endpoints require the token in the `Authorization` header:
```
Authorization: Bearer eyJhbGciOiJIUzI1NiJ9...
```

---

## 2. Roles and Access

| Role       | Data Access                                      |
|------------|--------------------------------------------------|
| `ADMIN`    | All 129 tables, all columns                      |
| `STAFF`    | All 129 tables, all columns                      |
| `DELEGATE` | 70 tables across 7 modules, restricted columns   |

The backend enforces this automatically. The agent simply passes the user's token —
it will only receive data that user is allowed to see.

### Modules available per role

| Module                | ADMIN / STAFF | DELEGATE |
|-----------------------|:---:|:---:|
| ANIMATION             | ✅ | ✅ |
| VENTES                | ✅ | ✅ |
| PRODUITS_STOCK        | ✅ | ✅ |
| DEMANDES              | ✅ | ✅ |
| REFERENTIELS          | ✅ | ✅ |
| DOCUMENTS_ENQUETES    | ✅ | ✅ |
| MARKETING_PROMO       | ✅ | ✅ |
| FINANCE               | ✅ | ❌ |
| ORGANISATION_TECHNIQUE| ✅ | ❌ |

---

## 3. Schema Discovery

### 3.1 Get Full Schema
Returns every module → table → column (with data type) visible to the caller's role.
**The agent should call this once at startup to understand the full data model.**

**Request**
```
GET /api/data/schema
Authorization: Bearer <token>
```

**Response structure**
```json
{
  "VENTES": {
    "ca_tot_vente": [
      { "name": "id",         "type": "int(11)",        "nullable": false, "key": "" },
      { "name": "ttc",        "type": "decimal(18,3)",  "nullable": true,  "key": "" },
      { "name": "ht",         "type": "decimal(18,3)",  "nullable": true,  "key": "" },
      { "name": "qte",        "type": "int(11)",        "nullable": true,  "key": "" },
      { "name": "art",        "type": "varchar(100)",   "nullable": true,  "key": "" },
      { "name": "cl",         "type": "varchar(1000)",  "nullable": false, "key": "" },
      { "name": "date",       "type": "date",           "nullable": true,  "key": "" },
      { "name": "dlg",        "type": "varchar(100)",   "nullable": true,  "key": "" },
      { "name": "fam",        "type": "varchar(100)",   "nullable": true,  "key": "" },
      { "name": "zone",       "type": "varchar(100)",   "nullable": true,  "key": "" },
      { "name": "created_at", "type": "datetime",       "nullable": false, "key": "" }
    ],
    "ca_prd_day": [ ... ]
  },
  "FINANCE": {
    "bl_fact": [ ... ]
  }
}
```

### 3.2 Get Columns for a Single Table
Returns typed column metadata for one table, filtered to what the caller can see.

**Request**
```
GET /api/meta/columns/{tableName}
Authorization: Bearer <token>
```

**Example**
```
GET /api/meta/columns/ca_tot_vente
```

**Response**
```json
[
  { "name": "id",   "type": "int(11)",       "nullable": false, "key": "" },
  { "name": "ttc",  "type": "decimal(18,3)", "nullable": true,  "key": "" },
  { "name": "date", "type": "date",          "nullable": true,  "key": "" }
]
```

---

## 4. Listing Available Tables and Modules

### 4.1 List All Accessible Tables
```
GET /api/data/tables
Authorization: Bearer <token>
```
**Response**
```json
["activite", "africa", "annimation_challenge", "ca_prd_day", "ca_tot_vente", "..."]
```

### 4.2 List Modules with Their Tables
```
GET /api/data/modules
Authorization: Bearer <token>
```
**Response**
```json
{
  "VENTES": ["ca_gamme_real_time", "ca_pdc_dlg", "ca_prd_day", "ca_tot_vente", "..."],
  "FINANCE": ["art_cogs", "bl_fact", "budget_conso", "..."]
}
```

### 4.3 List Tables in a Specific Module
```
GET /api/data/module/{moduleName}/tables
Authorization: Bearer <token>
```
**Example**
```
GET /api/data/module/VENTES/tables
```
**Response**
```json
["ca_gamme_real_time", "ca_pdc_dlg", "ca_prd_day", "ca_tot_vente"]
```

Valid module names: `ANIMATION`, `VENTES`, `PRODUITS_STOCK`, `DEMANDES`,
`REFERENTIELS`, `DOCUMENTS_ENQUETES`, `MARKETING_PROMO`, `FINANCE`, `ORGANISATION_TECHNIQUE`

---

## 5. Reading Table Data (Simple Pagination)

Use this endpoint for browsing a table without filters.

**Request**
```
GET /api/data/table/{tableName}?page=0&size=20
Authorization: Bearer <token>
```

| Parameter | Type    | Default | Max | Description              |
|-----------|---------|---------|-----|--------------------------|
| `page`    | integer | 0       | —   | Zero-based page number   |
| `size`    | integer | 20      | 500 | Rows per page            |

**Response**
```json
{
  "table":      "ca_tot_vente",
  "page":       0,
  "size":       20,
  "totalRows":  15420,
  "totalPages": 771,
  "columns":    ["id", "ttc", "ht", "qte", "art", "cl", "date", "dlg", "fam", "zone"],
  "rows": [
    { "id": 1, "ttc": 1200.500, "ht": 1000.000, "qte": 10, "art": "PROD001", "cl": "CL001", "date": "2024-03-15", "dlg": "DLG01", "fam": "FAM1", "zone": "Z1" },
    { "id": 2, "ttc": 850.000,  "ht": 708.333,  "qte": 5,  "art": "PROD002", "cl": "CL002", "date": "2024-03-15", "dlg": "DLG01", "fam": "FAM1", "zone": "Z1" }
  ]
}
```

---

## 6. Querying Table Data (Filters + Sort)

Use this endpoint when the agent needs to answer specific analytical questions.

**Request**
```
POST /api/data/query/{tableName}
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body**
```json
{
  "filters": [
    { "column": "dlg",  "operator": "eq",  "value": "DLG01" },
    { "column": "date", "operator": "gte", "value": "2024-01-01" },
    { "column": "date", "operator": "lte", "value": "2024-03-31" }
  ],
  "sort": {
    "column": "date",
    "direction": "desc"
  },
  "page": 0,
  "size": 50
}
```

**Response** — same structure as simple read:
```json
{
  "table":      "ca_tot_vente",
  "page":       0,
  "size":       50,
  "totalRows":  142,
  "totalPages": 3,
  "columns":    ["id", "ttc", "ht", "qte", "art", "cl", "date", "dlg", "fam", "zone"],
  "rows": [ ... ]
}
```

### 6.1 Filter Operators

| Operator      | SQL equivalent      | Value type              | Example                                                              |
|---------------|---------------------|-------------------------|----------------------------------------------------------------------|
| `eq`          | `=`                 | string / number         | `{ "column": "dlg", "operator": "eq", "value": "DLG01" }`           |
| `neq`         | `!=`                | string / number         | `{ "column": "etat", "operator": "neq", "value": 0 }`               |
| `gt`          | `>`                 | number / date           | `{ "column": "ttc", "operator": "gt", "value": 1000 }`              |
| `gte`         | `>=`                | number / date           | `{ "column": "date", "operator": "gte", "value": "2024-01-01" }`    |
| `lt`          | `<`                 | number / date           | `{ "column": "qte", "operator": "lt", "value": 5 }`                 |
| `lte`         | `<=`                | number / date           | `{ "column": "date", "operator": "lte", "value": "2024-12-31" }`    |
| `between`     | `BETWEEN ? AND ?`   | `[min, max]` array      | `{ "column": "date", "operator": "between", "value": ["2024-01-01","2024-12-31"] }` |
| `like`        | `LIKE ?`            | string with `%`         | `{ "column": "art", "operator": "like", "value": "PROD%" }`         |
| `notLike`     | `NOT LIKE ?`        | string with `%`         | `{ "column": "art", "operator": "notLike", "value": "%TEST%" }`     |
| `startsWith`  | `LIKE 'x%'`         | string (no `%` needed)  | `{ "column": "art", "operator": "startsWith", "value": "CREME" }`   |
| `endsWith`    | `LIKE '%x'`         | string (no `%` needed)  | `{ "column": "art", "operator": "endsWith", "value": "500MG" }`     |
| `contains`    | `LIKE '%x%'`        | string (no `%` needed)  | `{ "column": "art", "operator": "contains", "value": "AMOX" }`      |
| `in`          | `IN (...)`          | JSON array              | `{ "column": "zone", "operator": "in", "value": ["Z1","Z2","Z3"] }` |
| `notIn`       | `NOT IN (...)`      | JSON array              | `{ "column": "dlg", "operator": "notIn", "value": ["DLG99"] }`      |
| `isNull`      | `IS NULL`           | *(no value)*            | `{ "column": "fam", "operator": "isNull" }`                         |
| `isNotNull`   | `IS NOT NULL`       | *(no value)*            | `{ "column": "dlg", "operator": "isNotNull" }`                      |

All filters are combined with `AND`.

### 6.2 Sort Specification

```json
"sort": {
  "column":    "date",
  "direction": "desc"
}
```
- `direction`: `"asc"` (default) or `"desc"`
- Omit `sort` entirely for no ordering.

### 6.3 Pagination

```json
"page": 0,
"size": 50
```
- `page`: zero-based (first page = 0)
- `size`: max 500 rows per request
- Use `totalPages` from the response to know when to stop paginating

---

---

## 7. Aggregating Table Data (GROUP BY + Metrics)

The aggregate endpoint is the primary tool for KPIs, totals, rankings, breakdowns, and period analysis.
It supports computed date grouping, DISTINCT metrics, post-aggregation HAVING filters, and multi-column sorting.

**Request**
```
POST /api/data/aggregate/{tableName}
Authorization: Bearer <token>
Content-Type: application/json
```

### 7.1 Request Fields

| Field                 | Required         | Description                                                                          |
|-----------------------|------------------|--------------------------------------------------------------------------------------|
| `groupBy`             | At least one of  | Plain column names to group by. Example: `["dlg", "zone"]`                          |
| `groupByExpressions`  | groupBy or this  | Computed date grouping — see section 7.2                                             |
| `metrics`             | Yes              | Aggregation specs. Each needs `column`, `function`, `alias`, optional `distinct`    |
| `filters`             | No               | Pre-aggregation filters (WHERE clause) — same operators as `/query`                  |
| `having`              | No               | Post-aggregation filters (HAVING clause) — reference metric aliases                  |
| `sorts`               | No               | Multi-column sort array `[{column, direction}, ...]`                                 |
| `sort`                | No               | Single-column sort (legacy — overridden by `sorts` if both are present)              |
| `page`                | No               | Zero-based page (default 0)                                                          |
| `size`                | No               | Rows per page, max 500 (default 20)                                                  |

### 7.2 Aggregate Functions

| Function | Description           | `column` value     | `distinct` |
|----------|-----------------------|--------------------|------------|
| `SUM`    | Sum of values         | column name        | optional   |
| `COUNT`  | Count rows            | `"*"` or column    | optional   |
| `AVG`    | Average of values     | column name        | —          |
| `MIN`    | Minimum value         | column name        | —          |
| `MAX`    | Maximum value         | column name        | —          |

When `distinct: true`:
- `COUNT(DISTINCT col)` — counts unique values
- `SUM(DISTINCT col)` — sums unique values
- Cannot be combined with `COUNT(*)`

### 7.3 Computed Date Grouping (groupByExpressions)

Group by a date function applied to any date column.
Supported functions: `YEAR`, `MONTH`, `WEEK`, `DAY`, `QUARTER`, `DATE`

```json
{
  "column":   "date",
  "function": "MONTH",
  "alias":    "mois"
}
```
→ generates `MONTH(date) AS mois` in SELECT and GROUP BY.

You can mix `groupBy` and `groupByExpressions` in the same request:
```json
"groupBy":             ["dlg"],
"groupByExpressions":  [{ "column": "date", "function": "YEAR", "alias": "annee" }]
```
→ groups by delegate AND year simultaneously.

### 7.4 HAVING — Post-Aggregation Filter

Filter on computed metric values after grouping. Same operator syntax as `filters`.
Column must reference a metric alias, a raw `groupBy` column, or a computed alias.

```json
"having": [
  { "column": "ca_total", "operator": "gte", "value": 50000 }
]
```

**Important for pagination with HAVING:** When `having` is present, `totalRows` reflects the count
after HAVING filtering, not the total un-filtered group count.

### 7.5 Multi-Column Sort (sorts)

```json
"sorts": [
  { "column": "annee",    "direction": "asc"  },
  { "column": "ca_total", "direction": "desc" }
]
```
Overrides the legacy single-column `sort` field when both are present.

### 7.6 Response

Same structure as query/read endpoints:
```json
{
  "table":      "ca_tot_vente",
  "page":       0,
  "size":       50,
  "totalRows":  12,
  "totalPages": 1,
  "columns":    ["dlg", "annee", "ca_total", "nb_clients"],
  "rows": [
    { "dlg": "DLG01", "annee": 2024, "ca_total": 125000.0, "nb_clients": 48 },
    { "dlg": "DLG02", "annee": 2024, "ca_total":  98500.0, "nb_clients": 35 }
  ]
}
```

### 7.7 Usage Examples

**Total CA per delegate for Q1 2024, ranked:**
```json
POST /api/data/aggregate/ca_tot_vente
{
  "groupBy": ["dlg"],
  "metrics": [
    { "column": "ttc", "function": "SUM",   "alias": "ca_ttc" },
    { "column": "*",   "function": "COUNT", "alias": "nb_ventes" }
  ],
  "filters": [
    { "column": "date", "operator": "between", "value": ["2024-01-01", "2024-03-31"] }
  ],
  "sort": { "column": "ca_ttc", "direction": "desc" }
}
```

**Monthly CA breakdown for 2023:**
```json
POST /api/data/aggregate/ca_tot_vente
{
  "groupByExpressions": [
    { "column": "date", "function": "MONTH", "alias": "mois" }
  ],
  "metrics": [
    { "column": "ttc", "function": "SUM", "alias": "ca_total" },
    { "column": "qte", "function": "SUM", "alias": "qte_total" }
  ],
  "filters": [
    { "column": "date", "operator": "between", "value": ["2023-01-01", "2023-12-31"] }
  ],
  "sort": { "column": "mois", "direction": "asc" }
}
```

**CA by product by month in 2023:**
```json
POST /api/data/aggregate/ca_tot_vente
{
  "groupBy": ["art"],
  "groupByExpressions": [
    { "column": "date", "function": "YEAR",  "alias": "annee" },
    { "column": "date", "function": "MONTH", "alias": "mois"  }
  ],
  "metrics": [
    { "column": "ttc", "function": "SUM", "alias": "ca" }
  ],
  "filters": [
    { "column": "date", "operator": "between", "value": ["2023-01-01", "2023-12-31"] }
  ],
  "sorts": [
    { "column": "annee", "direction": "asc" },
    { "column": "mois",  "direction": "asc" },
    { "column": "ca",    "direction": "desc" }
  ]
}
```

**Unique clients per delegate (DISTINCT COUNT):**
```json
POST /api/data/aggregate/ca_tot_vente
{
  "groupBy": ["dlg"],
  "metrics": [
    { "column": "cl", "function": "COUNT", "alias": "nb_clients", "distinct": true },
    { "column": "ttc", "function": "SUM",  "alias": "ca_total" }
  ]
}
```

**Top delegates with CA > 100 000 (HAVING):**
```json
POST /api/data/aggregate/ca_tot_vente
{
  "groupBy": ["dlg"],
  "metrics": [
    { "column": "ttc", "function": "SUM", "alias": "ca_total" }
  ],
  "having": [
    { "column": "ca_total", "operator": "gte", "value": 100000 }
  ],
  "sort": { "column": "ca_total", "direction": "desc" }
}
```

---

## 8. Complete Usage Examples

### Example 1 — Sales by a delegate in Q1 2024
```json
POST /api/data/query/ca_tot_vente

{
  "filters": [
    { "column": "dlg",  "operator": "eq",  "value": "DLG05" },
    { "column": "date", "operator": "gte", "value": "2024-01-01" },
    { "column": "date", "operator": "lte", "value": "2024-03-31" }
  ],
  "sort": { "column": "date", "direction": "asc" },
  "page": 0,
  "size": 100
}
```

### Example 2 — Stock for specific products
```json
POST /api/data/query/art_stock_day

{
  "filters": [
    { "column": "article", "operator": "in", "value": ["PROD001", "PROD002", "PROD003"] },
    { "column": "date",    "operator": "gte", "value": "2024-03-01" }
  ],
  "sort": { "column": "date", "direction": "desc" },
  "page": 0,
  "size": 50
}
```

### Example 3 — High-value client outstanding balances
```json
POST /api/data/query/cl_reliquat

{
  "filters": [
    { "column": "mnt",  "operator": "gt", "value": 5000 }
  ],
  "sort": { "column": "mnt", "direction": "desc" },
  "page": 0,
  "size": 20
}
```

### Example 4 — Animation sessions in a date range
```json
POST /api/data/query/annimation_fiches

{
  "filters": [
    { "column": "date_annimation", "operator": "gte", "value": "2024-01-01" },
    { "column": "date_annimation", "operator": "lte", "value": "2024-06-30" },
    { "column": "etat",            "operator": "eq",  "value": 1 }
  ],
  "sort": { "column": "date_annimation", "direction": "desc" },
  "page": 0,
  "size": 50
}
```

### Example 5 — Products with names matching a pattern
```json
POST /api/data/query/art_prod_day

{
  "filters": [
    { "column": "article", "operator": "like", "value": "CREME%" },
    { "column": "date",    "operator": "gte",  "value": "2024-01-01" }
  ],
  "sort": { "column": "qte", "direction": "desc" },
  "page": 0,
  "size": 30
}
```

---

## 8. Error Responses

All errors return a JSON object with an `error` key.

| HTTP Status | Meaning                                              |
|-------------|------------------------------------------------------|
| `400`       | Invalid table name, column name, or operator         |
| `401`       | Missing or expired JWT token                         |
| `403`       | Role does not have access to this table/column       |
| `500`       | Server-side error (check `error` message)            |

**Example 403**
```json
{ "error": "Accès refusé à la table : cl_reglement" }
```

**Example 400**
```json
{ "error": "Opérateur invalide : unknown_op" }
```

**Example 400 (IN with wrong value type)**
```json
{ "error": "L'opérateur 'in' requiert une liste JSON" }
```

---

## 9. Recommended Agent Workflow

```
1. POST /api/auth/login          → obtain accessToken + role
2. GET  /api/data/schema         → load full schema (modules → tables → typed columns)
3. Based on user question:
     a. Identify relevant table(s) from schema
     b. KPI / summary / ranking / period breakdown?
           → POST /api/data/aggregate/{table}
             • groupBy or groupByExpressions (YEAR/MONTH/WEEK/DAY/QUARTER/DATE)
             • metrics with optional distinct:true
             • filters (pre-aggregation WHERE)
             • having (post-aggregation HAVING on metric aliases)
             • sorts (multi-column ordering)
     c. Period comparison / growth rate?
           → Make two aggregate calls (one per period) and merge client-side,
             or use the compare_periods agent tool which does this automatically.
     d. Raw rows / detailed listing / search?
           → POST /api/data/query/{table} with filters + sort
     e. If totalPages > 1, paginate with page=1, page=2, ... until done
4. When accessToken expires → POST /api/auth/refresh → continue
```

---

## 10. Data Types Reference

| MySQL Type         | Example values                    | Notes                          |
|--------------------|-----------------------------------|--------------------------------|
| `int(N)`           | `1`, `42`, `null`                 | Use numeric value in filters   |
| `decimal(M,D)`     | `1200.500`, `0.000`               | Use numeric value in filters   |
| `float`            | `3.14`, `100.0`                   | Use numeric value in filters   |
| `varchar(N)`       | `"DLG01"`, `"PROD001"`            | Use string value in filters    |
| `text`             | `"long text..."`                  | Supports `like` operator       |
| `date`             | `"2024-03-15"`                    | Format: `YYYY-MM-DD`           |
| `datetime`         | `"2024-03-15 14:30:00"`           | Format: `YYYY-MM-DD HH:MM:SS`  |
| `timestamp`        | `"2024-03-15 14:30:00"`           | Same as datetime               |
| `tinyint(1)`       | `0` or `1`                        | Boolean-like flag              |
| `enum`             | `"ADMIN"`, `"DELEGATE"`           | Use exact string value         |

---

## 11. Important Constraints

- **Max page size**: 500 rows per request
- **Column names in filters and sort must exactly match** the column names returned by `/api/data/schema`
- **All filter conditions are AND-combined** — there is no OR at the moment
- **Date values must be strings** in `YYYY-MM-DD` format
- **The `like` / `notLike` operators** require the `%` wildcard explicitly: `"PROD%"` matches anything starting with PROD
- **The `startsWith` / `endsWith` / `contains` operators** do NOT need `%` — the backend adds them automatically
- **The `in` / `notIn` operators** value must be a JSON array, never a single value
- **The `between` operator** value must be a two-element array: `[start, end]` (inclusive)
- **The `isNull` / `isNotNull` operators** do not require a `value` field
- **aggregate `groupBy` or `groupByExpressions`**: at least one is required — the endpoint will reject a request with neither
- **HAVING columns** must reference a metric alias, a raw `groupBy` column, or a computed `groupByExpressions` alias
- **Sensitive columns** (`grm_users.password`, `grm_users.pass`) are never returned regardless of role
