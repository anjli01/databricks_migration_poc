# Approach Comparison: Replacing Alteryx Analytical Apps
## Databricks Apps (Streamlit) vs. Custom External Website

**Context:** Migration of Alteryx Analytical Apps (specifically BenchmarkCalculationApp_Prod.yxwz) to Databricks.  
**Decision required:** Which frontend approach to use for stakeholder input interfaces.

---

## The Two Approaches at a Glance

### Approach A — Databricks Apps (Streamlit)
Host a Python-based web app (Streamlit/Dash/Flask) **directly inside Databricks**. Stakeholders access it via a URL served from your Databricks workspace. The app talks to Databricks natively — no proxy, no extra auth layer.

### Approach B — Custom External Website
Build a standalone website (HTML/JS or React) hosted on a separate server (Azure App Service, AWS, etc.) with a dedicated backend (FastAPI/Express) that proxies API calls to Databricks Jobs REST API.

---

## Architecture Comparison

```
APPROACH A — Databricks Apps (Streamlit)
─────────────────────────────────────────
  Stakeholder Browser
        │
        │  HTTPS (Databricks-hosted URL)
        ▼
  Databricks App (Streamlit)          ← lives inside Databricks
        │
        │  Internal SDK call (no network hop)
        ▼
  Databricks Job / Notebook


APPROACH B — Custom External Website
─────────────────────────────────────────
  Stakeholder Browser
        │
        │  HTTPS (your domain, e.g. benchmarks.company.com)
        ▼
  Your Frontend (HTML/JS)             ← hosted separately
        │
        │  HTTPS API call
        ▼
  Your Backend Proxy (FastAPI)        ← hosted separately
        │
        │  HTTPS + OAuth token
        ▼
  Databricks REST API (/api/2.1/jobs/run-now)
        │
        ▼
  Databricks Job / Notebook
```

Approach A has **2 layers**. Approach B has **4 layers**. Every additional layer is a failure point, a maintenance burden, and a security surface.

---

## Detailed Comparison

### 1. Setup & Time-to-First-Working-Version

| | Approach A | Approach B |
|---|---|---|
| Lines of code to trigger a job | ~10 (SDK call) | ~80 (backend + frontend combined) |
| Infrastructure to provision | Zero | Server + SSL cert + domain + secrets manager |
| Time to first working prototype | **½ day** | 3–5 days |
| Auth for stakeholders | Databricks login (already exists) | Must build/configure separately |

**Verdict:** Approach A wins decisively on speed and simplicity.

---

### 2. Authentication & Security

**Approach A:**  
- Databricks handles all authentication. Stakeholders log in with their existing Databricks credentials.  
- Permissions are inherited — if a user can't run a job in Databricks, they can't run it from the app either. You don't need to build or maintain any auth.
- No credentials ever touch your app code.

**Approach B:**  
- You **must** build user authentication from scratch (or integrate SSO like Azure AD).  
- You **must** store a Service Principal secret or PAT somewhere server-side and manage its lifecycle.  
- You **must** ensure the backend server is not publicly accessible without auth.  
- A misconfiguration in any of these layers = security incident.

**Verdict:** Approach A is structurally more secure. Approach B has more attack surface and requires deliberate, correct security engineering. It's not that it's impossible — it's that it requires sustained discipline to keep secure.

---

### 3. Maintenance Burden

**Approach A:**  
- One codebase: `benchmark_app.py`.  
- Databricks manages the runtime, scaling, and SSL.  
- When your job parameters change, you change one file.

**Approach B:**  
- Frontend code (HTML/JS).  
- Backend server code (FastAPI/Express).  
- Server infrastructure (updates, patches, downtime).  
- SSL certificate renewals.  
- OAuth token refresh logic.  
- Secrets rotation.  
- CORS policy maintenance.  

Every one of these is a maintenance task that someone has to own forever — not just during the build.

**Verdict:** Approach A has a fraction of the ongoing maintenance overhead.

---

### 4. UI Capability (Can It Actually Replicate the Alteryx App?)

This is where people assume Approach B wins because "you can build anything in HTML." That's technically true, but here is what your Alteryx App actually needs:

| Filter Element | Streamlit Widget | Custom Website |
|---|---|---|
| Multi-select + "All years" toggle | `st.multiselect()` + `st.checkbox()` — built-in | Build from scratch in JS |
| Tenure type checkboxes with "All tenures" | Same as above | Build from scratch |
| Conditional text field (only for non-Master) | `st.text_input(disabled=...)` | Build + JS logic |
| Select/Exclude/Export tabs | `st.tabs()` — one line | Build tab component in JS/CSS |
| Status polling after job trigger | `st.spinner()` + `st.button()` | Build polling loop + UI state management |
| Parameter display/audit after run | `st.json()` — one line | Build JSON display component |

Streamlit covers every filter type in your Alteryx App with native, tested widgets. A custom website can match it — but you are building and testing each of these yourself.

**Verdict:** Approach A can replicate this specific app without compromise. Approach B can too, but takes 5–10x more effort for no user-facing benefit.

---

### 5. Performance

**Approach A — honest weaknesses:**  
- Streamlit re-runs the entire script on every widget interaction. For complex apps with many filters, this can feel slow.  
- Each Databricks App instance runs on a single server process. Concurrent users share resources.  
- Streamlit is not built for pixel-perfect animations or highly interactive data visualisations (for that, use Dash or Panel).

**Approach B — honest strengths:**  
- A React/Next.js frontend is genuinely faster for UI responsiveness.  
- You can implement debouncing, client-side caching, and instant UI feedback that Streamlit cannot easily match.  
- Scales independently of Databricks infrastructure.

**For a filter form + job trigger use case, this performance gap is irrelevant.** You are not building a real-time trading dashboard. Users fill a form, click Run, and wait for a job that takes minutes. Streamlit's re-render latency (typically <200ms) is not a problem here.

---

### 6. Cost

**Approach A:**  
- Databricks Apps is billed as DBUs when the app is active. For a lightly used internal tool, this is minimal (often < $5/month equivalent).
- No server, no domain, no SSL, no hosting cost.

**Approach B:**  
- Azure App Service / AWS EC2: $15–$80/month depending on tier.
- SSL certificate, domain registration: $10–$50/year.
- Developer time for setup, maintenance, and security: the dominant cost.

**Verdict:** Approach A is cheaper in both direct cost and engineering time.

---

## When to Use Each Approach — Decision Table

| Scenario | Use Approach A (Streamlit) | Use Approach B (Custom Website) |
|---|---|---|
| Users are internal, have Databricks access | ✅ | — |
| Users are external, no Databricks login possible | — | ✅ |
| Public-facing URL required (no login) | — | ✅ |
| Pixel-perfect corporate branding mandatory | Possible but limited | ✅ |
| Team has no backend/server engineering capacity | ✅ | — |
| App is a filter form + run job | ✅ | — |
| App needs real-time streaming data in the UI | ❌ | ✅ |
| App integrates with non-Databricks external APIs | Possible | ✅ |
| Quick prototype needed in days | ✅ | — |
| Need to embed in existing company web portal | — | ✅ |
| Regulatory requirement to isolate Databricks from internet | Depends on setup | ✅ |

---

## Applied to Your Case: BenchmarkCalculationApp

Your app has:
- **Internal stakeholders** → they already have (or can be given) Databricks workspace access
- **A filter form** (years, tenure, property use, countries, KPIs) → every single one of these is a standard Streamlit widget
- **A "Run Workflow" trigger** → one SDK call in Python
- **No public access requirement** → no external hosting needed
- **No real-time streaming** → job runs in the background; stakeholders check back

**Approach A (Streamlit) is the right choice for this app. Not because it is always better, but because it directly fits every constraint and requirement of this specific use case without adding unnecessary complexity.**

Choosing Approach B here would mean building and maintaining a backend server, an auth system, a proxy layer, and a complete JavaScript frontend — all to deliver identical functionality to the stakeholder. That engineering effort has no ROI in this context.

---

## Where Approach B (Custom Website) Would Win

To be direct: if any of these were true, the answer would flip:

1. **Stakeholders cannot be given Databricks access** — e.g., clients, external consultants, or users in a different organisation with no Databricks licence. In this case, you have no choice but to build an external app.

2. **The UI needs to be embedded inside an existing internal company portal or SharePoint** — Databricks Apps cannot be iframed into external sites easily.

3. **The app needs to display data interactively in ways Streamlit cannot** — e.g., complex custom D3 charts, drag-and-drop interfaces, or canvas-based visualisations.

4. **You need to serve thousands of concurrent users** — Databricks Apps has limits on concurrent sessions; a properly scaled backend can handle this better.

5. **The company has a standard tech platform (e.g., Azure Static Web Apps + Azure Functions)** and engineering capacity to build on it — then the custom website fits into existing infrastructure and tooling.

---

## Recommendation

**Use Databricks Apps (Streamlit) for the Benchmark Calculation App.**

Build the custom website approach only if stakeholder access to Databricks is not possible, or if a future version of the app requires capabilities that Streamlit cannot deliver.

The decision should be driven by user access requirements first, UI requirements second. Everything else is secondary.

---

## Files

| File | Description |
|---|---|
| `benchmark_app.py` | Working Streamlit implementation of the BenchmarkCalculationApp |
| `implementation_plan.md` | Full technical plan for the custom website approach (for reference) |

---

*Document prepared as part of Alteryx → Databricks migration planning.*
