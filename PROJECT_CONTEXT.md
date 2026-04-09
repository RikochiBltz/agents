# MediNote Backend — Project Context for New Sessions

> Hand this file to any new Claude session to get full context on what exists,
> what is done, and what still needs to be built.

---

## 1. What This Project Is

A **Spring Boot backend** that serves as the **sole data source** for a
role-aware multi-agent CRM chatbot. The AI system architecture is:

```
User
 └─► AI Orchestrator
       └─► Data Agent  ◄──► THIS BACKEND (port 8081)
             └─► KPI Agent / Report Agent / Analysis Agent
                   └─► Formatted response to user
```

The Data Agent is the **only** component that talks to the database.
KPI, Report, and Analysis agents receive already-fetched data from the
Data Agent — they never call the backend or the DB directly.

---

## 2. Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Java 17 |
| Framework | Spring Boot 3.5.10 |
| Database | MySQL — database named `vital` |
| Auth | JWT (stateless) via `JwtAuthFilter` |
| Build | Maven (multi-module: `MediNoteProject/backend`) |
| Other services | Eureka (port 8761), Gateway (port 8085) — not relevant to dataagent work |

Backend runs on **port 8081**.

---

## 3. Database Facts

- Database name: `vital`
- **129 business tables** — no foreign key constraints enforced
- Tables are organized into 9 business modules (see Section 6)
- Do **NOT** alter the database schema — no migrations, no new tables, no enum changes
- The `grm_users` table has sensitive columns `password` and `pass` — always excluded from query results

---

## 4. User Roles

Three roles exist in `users.role` enum:

| Role | Access Level |
|------|-------------|
| `ADMIN` | Full access — all 9 modules, all tables, all columns |
| `STAFF` | Full access — same as ADMIN |
| `DELEGATE` | Restricted — 7 modules only, column-level restrictions per table |

**Important:** There is no `ENTREPRISE` role. There is no `DELEGUE` role.
The exact strings are `ADMIN`, `STAFF`, `DELEGATE`.

---

## 5. Authentication — Current State

**Auth is currently DISABLED for testing.** The production code is commented
out, NOT deleted. To re-enable:

**`SecurityConfig.java`** — swap these two blocks:
```java
// TESTING (active now):
.anyRequest().permitAll()

// PRODUCTION (commented out):
// .requestMatchers("/api/auth/login", ...).permitAll()
// .anyRequest().authenticated()
// .addFilterBefore(jwtAuthFilter, ...)
```

**`GenericDataController.java`** and **`DynamicQueryService.java`** — both
have `extractRole()` methods that currently return `"ADMIN"` when no auth
is present. Production versions throw `SecurityException` — also commented.

The `users` table had an issue that caused auth problems — needs investigation
before re-enabling. All auth infrastructure (JWT, refresh tokens, password
reset) exists and is complete.

---

## 6. The 9 Data Modules

Each module groups related tables. The `DataModule` enum and
`ModuleRegistryService` define this mapping.

| Module | Tables (count) | DELEGATE access |
|--------|---------------|-----------------|
| `ANIMATION` | 15 | Yes |
| `VENTES` | 14 | Yes |
| `PRODUITS_STOCK` | 6 | Yes |
| `DEMANDES` | 10 | Yes |
| `REFERENTIELS` | 12 | Yes |
| `DOCUMENTS_ENQUETES` | 9 | Yes |
| `MARKETING_PROMO` | 4 | Yes |
| `FINANCE` | 21 | **No** |
| `ORGANISATION_TECHNIQUE` | 38 | **No** |

DELEGATE is blocked from FINANCE and ORGANISATION_TECHNIQUE entirely.
For the 7 allowed modules, DELEGATE has column-level restrictions defined
in `AccessPolicyService.DELEGATE_ALLOWED_COLUMNS`.

---

## 7. Project File Structure

```
MediNoteProject/
└── backend/
    └── src/main/java/com/medinote/medinotebackend/
        │
        ├── MediNoteApplication.java              — entry point
        │
        ├── auth/                                 — authentication layer
        │   ├── AuthController.java               — /api/auth/* endpoints
        │   ├── LoginRequest / LoginResponse
        │   ├── RefreshRequest / RefreshResponse
        │   ├── LogoutRequest
        │   └── reset/                            — password reset flow
        │       ├── PasswordResetService.java
        │       ├── PasswordResetToken.java
        │       └── PasswordResetTokenRepository.java
        │
        ├── security/
        │   ├── SecurityConfig.java               — *** AUTH DISABLED (testing mode) ***
        │   ├── JwtAuthFilter.java                — JWT validation filter
        │   ├── JwtService.java                   — token generation/validation
        │   ├── CustomUserDetailsService.java     — loads user from DB
        │   ├── RefreshTokenService.java          — refresh token management
        │   └── PasswordConfig.java               — BCrypt bean
        │
        ├── user/
        │   ├── User.java                         — entity: id, email, password, fullName, role, enabled
        │   ├── Role.java                         — enum: ADMIN, STAFF, DELEGATE
        │   ├── UserController.java               — /api/users/** (ADMIN only)
        │   ├── UserRepository.java
        │   ├── UserService.java
        │   └── dto/UserRequest, UserResponse
        │
        ├── dataagent/                            — THE CORE: AI data access layer
        │   │
        │   ├── model/
        │   │   └── DataModule.java               — enum of 9 modules
        │   │
        │   ├── dto/                              — request/response shapes
        │   │   ├── ColumnMetaDto.java            — { name, type, nullable, key }
        │   │   ├── FilterCondition.java          — { column, operator, value }
        │   │   ├── SortSpec.java                 — { column, direction }
        │   │   ├── QueryRequest.java             — body for /query endpoint
        │   │   ├── AggregateMetric.java          — { column, function, alias }
        │   │   ├── AggregateRequest.java         — body for /aggregate endpoint
        │   │   └── TableResponseDto.java         — unified response for all data endpoints
        │   │
        │   ├── service/
        │   │   ├── ModuleRegistryService.java    — maps modules → table name lists
        │   │   ├── AccessPolicyService.java      — role-based access rules
        │   │   ├── MetadataService.java          — reads column info from information_schema
        │   │   └── DynamicQueryService.java      — builds + executes all SQL queries
        │   │
        │   └── controller/
        │       ├── GenericDataController.java    — all /api/data/* endpoints
        │       └── MetadataTestController.java   — /api/meta/columns/{table}
        │
        ├── config/
        │   ├── DataSeeder.java                   — seeds initial admin user on startup
        │   └── MinioConfig.java                  — file storage config
        │
        ├── files/
        │   └── FileController.java               — /api/files/* (MinIO)
        │
        ├── mail/
        │   └── EmailService.java                 — password reset emails
        │
        └── storage/
            └── FileStorageService.java
```

---

## 8. All API Endpoints

### Auth (`/api/auth`)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/login` | Login → returns `accessToken` + optional `refreshToken` |
| POST | `/api/auth/refresh` | Exchange refresh token for new access token |
| POST | `/api/auth/logout` | Invalidate refresh token |
| POST | `/api/auth/forgot-password` | Send password reset email |
| POST | `/api/auth/reset-password` | Apply new password with reset token |

### Data Agent (`/api/data`) — the core
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/data/tables` | List all tables the caller's role can read |
| GET | `/api/data/modules` | All modules + their tables for caller's role |
| GET | `/api/data/module/{name}/tables` | Tables in one specific module |
| GET | `/api/data/table/{tableName}?page=0&size=20` | Raw paginated read, no filters |
| GET | `/api/data/schema` | Full schema: all visible modules → tables → typed columns |
| POST | `/api/data/query/{tableName}` | Filtered + sorted raw rows |
| POST | `/api/data/aggregate/{tableName}` | GROUP BY + SUM/COUNT/AVG/MIN/MAX |

### Metadata (`/api/meta`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/meta/columns/{tableName}` | Typed column list for one table |

### Users (`/api/users`) — ADMIN only
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/users` | List all users |
| GET | `/api/users/{id}` | Get one user |
| POST | `/api/users` | Create user |
| PUT | `/api/users/{id}` | Update user |
| DELETE | `/api/users/{id}` | Delete user |

---

## 9. Key Service: DynamicQueryService

This is the most important service. It handles all SQL generation safely.

**Security model:**
- All table names and column names validated against `SAFE_SQL_NAME` regex (`^[a-zA-Z0-9_]+$`)
- Columns validated against the caller's visible columns list before use — prevents both injection and unauthorized access
- Filter values passed as JDBC `?` parameters — never concatenated
- `in` operator expands to `(?, ?, ?)` with proper parameter binding
- Sensitive columns (`grm_users.password`, `grm_users.pass`) excluded at `resolveColumns()` level for ALL roles

**Methods:**
- `getAllowedTables(auth)` — tables the role can read
- `readTable(tableName, page, size, auth)` — simple paginated read
- `queryTable(tableName, request, auth)` — filtered + sorted query
- `aggregateTable(tableName, request, auth)` — GROUP BY aggregation

**Filter operators:** `eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `like`, `in`

**Aggregate functions:** `SUM`, `COUNT`, `AVG`, `MIN`, `MAX`

**Pagination:** max 500 rows per page, returns `totalRows` and `totalPages`

---

## 10. Key Service: AccessPolicyService

Enforces role-based access at the service layer.

- `canReadTable(role, tableName)` → boolean
- `canAccessModule(role, module)` → boolean
- `getAllowedColumns(role, tableName)` → `List<String>` (returns `["*"]` for full access)
- `getAllowedModulesWithTables(role)` → `Map<DataModule, List<String>>`
- `getExcludedColumns(tableName)` → sensitive columns to always strip
- `hasFullAccess(role)` → true for ADMIN and STAFF

---

## 11. Unified Response Format

Every data endpoint returns `TableResponseDto`:

```json
{
  "table":      "ca_tot_vente",
  "page":       0,
  "size":       50,
  "totalRows":  1430,
  "totalPages": 29,
  "columns":    ["dlg", "zone", "ttc", "qte"],
  "rows": [
    { "dlg": "DLG01", "zone": "ARIANA", "ttc": 1250.000, "qte": 10 }
  ]
}
```

---

## 12. Query Endpoint Examples

### Raw filtered query
```json
POST /api/data/query/ca_tot_vente
{
  "filters": [
    { "column": "zone",  "operator": "in",  "value": ["ARIANA", "SFAX 1A"] },
    { "column": "date",  "operator": "gte", "value": "2024-01-01" }
  ],
  "sort": { "column": "date", "direction": "desc" },
  "page": 0,
  "size": 50
}
```

### Aggregation (KPI)
```json
POST /api/data/aggregate/ca_tot_vente
{
  "groupBy": ["dlg", "zone"],
  "metrics": [
    { "column": "ttc", "function": "SUM",   "alias": "total_ttc"  },
    { "column": "qte", "function": "SUM",   "alias": "total_qte"  },
    { "column": "*",   "function": "COUNT", "alias": "nb_ventes"  },
    { "column": "ttc", "function": "AVG",   "alias": "avg_ttc"    }
  ],
  "filters": [
    { "column": "date", "operator": "gte", "value": "2024-01-01" }
  ],
  "sort": { "column": "total_ttc", "direction": "desc" },
  "page": 0,
  "size": 20
}
```

---

## 13. What Is Complete

- [x] Full dataagent layer (metadata, access policy, dynamic query, aggregation)
- [x] Role enforcement for all 3 roles (ADMIN, STAFF, DELEGATE)
- [x] Column-level restrictions for DELEGATE on all 7 allowed modules
- [x] Sensitive column exclusion (password fields never returned)
- [x] SQL injection protection on all inputs
- [x] Schema discovery endpoint (`/api/data/schema`)
- [x] Filtered query endpoint (`/api/data/query/{table}`)
- [x] Aggregation endpoint (`/api/data/aggregate/{table}`) — SUM/COUNT/AVG/MIN/MAX
- [x] Pagination with `totalRows` + `totalPages` in every response
- [x] Full auth infrastructure (JWT, refresh tokens, password reset)
- [x] Users CRUD (ADMIN only)
- [x] API documentation at `C:\backend PI\MediNote\AGENT_API_DOCUMENTATION.md`

---

## 14. What Still Needs to Be Built

### On the backend (minor gaps)
- [ ] **Re-enable authentication** — `SecurityConfig.java` has production code
  commented. Needs the `users` table issue diagnosed first.
- [ ] **Distinct values endpoint** — `GET /api/data/distinct/{table}/{column}`
  returns unique values for a column (e.g. all zone names, all delegate names).
  Useful for the agent to enumerate valid filter values without guessing.

### The agentic system (not yet started)
This is the main remaining work. The backend is ready to serve it.

**Orchestrator agent**
- Receives natural language from the user
- Understands intent and determines: which module, which table, what aggregation
- Delegates to Data Agent with a structured API call spec
- Routes the result to the right specialized agent

**Data Agent**
- Reads `GET /api/data/schema` once at startup to know the data model
- Translates Orchestrator instructions into the correct API call (query or aggregate)
- Calls the backend, returns raw `TableResponseDto`
- Handles pagination if `totalPages > 1`

**KPI Agent**
- Receives pre-aggregated rows from Data Agent
- Computes ratios, growth rates, rankings, comparisons
- Never calls the backend

**Report Agent**
- Receives structured data from Data Agent
- Formats into a readable narrative report
- Never calls the backend

**Analysis Agent**
- Receives data from Data Agent
- Detects trends, anomalies, outliers
- Never calls the backend

---

## 15. Important Constraints for Future Work

1. **Do not alter the `vital` database** — no schema changes, no enum additions
2. **Auth code is commented, not deleted** — always restore from comments, never rewrite from scratch
3. **Role strings must match DB exactly**: `ADMIN`, `STAFF`, `DELEGATE`
4. **No ENTREPRISE role exists** in the DB
5. **`grm_users.password` and `grm_users.pass`** must never appear in any API response
6. **Max page size is 500** — enforced in `DynamicQueryService`
7. The backend is on branch `dev2` — 2 commits ahead of `origin/dev2`, not pushed

---

## 16. Reference Files

| File | Purpose |
|------|---------|
| `C:\backend PI\MediNote\AGENT_API_DOCUMENTATION.md` | Full API docs for the Data Agent system prompt |
| `C:\backend PI\MediNote\PROJECT_CONTEXT.md` | This file |
| `C:\backend PI\MediNote\MediNoteProject\backend\src\main\java\com\medinote\medinotebackend\dataagent\` | All dataagent source code |
| `C:\backend PI\MediNote\columns.json` | Raw column export from the `vital` database |
