# Building the Benchmark Calculation App with Streamlit on Databricks Apps

**Goal:** Replace the Alteryx `BenchmarkCalculationApp_Prod.yxwz` with a Streamlit app hosted inside Databricks.  
**End result:** Stakeholders open a URL, fill in filters (years, tenure, property use, KPIs etc.), click **Run Workflow**, and the Databricks job executes with those parameters.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Databricks Setup](#2-databricks-setup)
   - 2.1 [Create / Verify the Databricks Job](#21-create--verify-the-databricks-job)
   - 2.2 [Add Parameters to the Notebook](#22-add-parameters-to-the-notebook)
   - 2.3 [Create a Service Principal (optional but recommended)](#23-create-a-service-principal-optional-but-recommended)
3. [Project Folder Structure](#3-project-folder-structure)
4. [The Streamlit App — Full Code Walkthrough](#4-the-streamlit-app--full-code-walkthrough)
   - 4.1 [Page Config & Styling](#41-page-config--styling)
   - 4.2 [Tabs (Select / Exclude / Export)](#42-tabs-select--exclude--export)
   - 4.3 [Filter Sections](#43-filter-sections)
   - 4.4 [Run Workflow Button & Job Trigger](#44-run-workflow-button--job-trigger)
   - 4.5 [Status Polling](#45-status-polling)
5. [app.yaml — Databricks App Configuration](#5-appyaml--databricks-app-configuration)
6. [requirements.txt](#6-requirementstxt)
7. [Deploying to Databricks Apps](#7-deploying-to-databricks-apps)
   - 7.1 [Via Databricks UI](#71-via-databricks-ui)
   - 7.2 [Via Databricks CLI](#72-via-databricks-cli)
8. [How Parameters Reach the Notebook](#8-how-parameters-reach-the-notebook)
9. [Granting Stakeholder Access](#9-granting-stakeholder-access)
10. [Testing Checklist](#10-testing-checklist)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Prerequisites

Before you write a single line of code, confirm all of these are in place:

| Requirement | Where to get it | Notes |
|---|---|---|
| Databricks workspace | Your org's Databricks URL | e.g. `https://adb-xxxx.azuredatabricks.net` |
| Databricks job created | Workflows → Jobs → Create Job | Note the **Job ID** |
| `databricks-sdk` Python package | `pip install databricks-sdk` | Already available inside Databricks Apps runtime |
| `streamlit` Python package | `pip install streamlit` | Already available inside Databricks Apps runtime |
| Databricks Apps feature enabled | Ask your Databricks admin | Required for deployment |
| Your user account has `Can Manage` on the job | Workflows → Job → Permissions | Needed to test locally |

---

## 2. Databricks Setup

### 2.1 Create / Verify the Databricks Job

1. In your Databricks workspace, go to **Workflows → Jobs**
2. Either create a new job or open your existing benchmark job
3. Note the **Job ID** — you'll find it in the URL:  
   `https://adb-xxxx.azuredatabricks.net/#job/`**`123456789`**`/...`
4. Under the job's **Tasks**, ensure there is a notebook task pointing to your benchmark notebook
5. Open **Job → Edit → Parameters** and confirm or add parameters (see 2.2 below)

### 2.2 Add Parameters to the Notebook

Your Databricks notebook must be set up to **receive** the parameters the Streamlit app will send. Add this at the top of the notebook:

```python
# ── At the very top of your benchmark notebook ──────────────────────────────
import json

# Declare widgets — these act as the parameter receivers
dbutils.widgets.text("benchmark_type",  "Test Benchmark")
dbutils.widgets.text("benchmark_name",  "")
dbutils.widgets.text("years",           "[2025]")
dbutils.widgets.text("tenure",          "[]")
dbutils.widgets.text("property_use",    "[]")
dbutils.widgets.text("countries",       "[\"UK\"]")
dbutils.widgets.text("cities",          "[]")
dbutils.widgets.text("buildings",       "[]")
dbutils.widgets.text("kpis",            "[]")
dbutils.widgets.text("export_format",   "Excel (.xlsx)")
dbutils.widgets.text("export_path",     "sandbox.benchmark_output")
dbutils.widgets.text("confirm_master",  "false")

# ── Read the values ──────────────────────────────────────────────────────────
benchmark_type  = dbutils.widgets.get("benchmark_type")
benchmark_name  = dbutils.widgets.get("benchmark_name")
years           = json.loads(dbutils.widgets.get("years"))          # list
tenure          = json.loads(dbutils.widgets.get("tenure"))         # list
property_use    = json.loads(dbutils.widgets.get("property_use"))   # list
countries       = json.loads(dbutils.widgets.get("countries"))      # list
cities          = json.loads(dbutils.widgets.get("cities"))         # list
buildings       = json.loads(dbutils.widgets.get("buildings"))      # list
kpis            = json.loads(dbutils.widgets.get("kpis"))           # list
export_format   = dbutils.widgets.get("export_format")
export_path     = dbutils.widgets.get("export_path")
confirm_master  = dbutils.widgets.get("confirm_master") == "true"

# ── Verify what was received (helpful during testing) ───────────────────────
print(f"Benchmark Type : {benchmark_type}")
print(f"Years          : {years}")
print(f"Tenure         : {tenure}")
print(f"Countries      : {countries}")
print(f"KPIs           : {kpis}")
```

> **Important:** The `json.loads()` calls are necessary because the Jobs API only passes string values. Lists are serialised to JSON strings by the Streamlit app before sending, and deserialised here on receipt.

### 2.3 Create a Service Principal (Optional but Recommended)

Using a Service Principal is more secure than using your personal PAT because it has its own identity, scoped permissions, and rotatable credentials.

**Steps:**

1. Go to **Databricks Account Console** → `https://accounts.azuredatabricks.net`
2. Click **Service Principals → Add service principal**
3. Give it a name, e.g. `benchmark-app-sp`
4. Click **Generate secret** → copy the **Client ID** and **Client Secret** (shown once only)
5. Back in your workspace, go to **Workflows → Your Job → Permissions**
6. Add the service principal with **Can Manage Run** permission

> **Inside Databricks Apps, you don't need to configure credentials manually.** The app authenticates as the user running it. Service Principals are only needed if you run the app externally or want a shared service account.

---

## 3. Project Folder Structure

```
benchmark-app/
│
├── app.py                  ← Main Streamlit application
├── app.yaml                ← Databricks App configuration file
├── requirements.txt        ← Python dependencies
└── README.md               ← (optional) usage notes for your team
```

Create this folder locally or directly in your Databricks workspace using the file browser.

---

## 4. The Streamlit App — Full Code Walkthrough

Create a file called `app.py`. Below is the full code with explanations for each section.

### 4.1 Page Config & Styling

```python
import streamlit as st
from databricks.sdk import WorkspaceClient
import json

st.set_page_config(
    page_title="Benchmark Calculation App",
    page_icon="📊",
    layout="wide"       # Use full browser width — better for filter-heavy apps
)

# Custom CSS — keeps the app looking clean and professional
st.markdown("""
<style>
    .stApp { background-color: #f5f6fa; }
    
    .app-header {
        background: linear-gradient(90deg, #1a1a2e, #16213e);
        color: white;
        padding: 20px 30px;
        border-radius: 10px;
        margin-bottom: 24px;
    }
    
    .section-label {
        font-size: 15px;
        font-weight: 600;
        color: #2c3e50;
        border-left: 4px solid #4f8ef7;
        padding-left: 10px;
        margin: 16px 0 8px 0;
    }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="app-header">
    <h2 style="margin:0">📊 Benchmark Calculation App</h2>
    <p style="margin:4px 0 0; opacity:0.75">
        Select filters and run the benchmark workflow
    </p>
</div>
""", unsafe_allow_html=True)
```

### 4.2 Tabs (Select / Exclude / Export)

These mirror the **Select | Exclude | Export** tabs in the Alteryx app.

```python
tab_select, tab_exclude, tab_export = st.tabs(["📋 Select", "🚫 Exclude", "📤 Export"])
```

All filter code goes inside `with tab_select:` below.

### 4.3 Filter Sections

```python
with tab_select:

    # ── Benchmark Type ─────────────────────────────────────────────────────────
    st.markdown('<p class="section-label">Define key benchmark parameters</p>',
                unsafe_allow_html=True)

    col1, col2 = st.columns(2)

    with col1:
        benchmark_type = st.selectbox(
            "Select Benchmark Type",
            options=["Test Benchmark", "Custom Benchmark", "Master Office Benchmark"]
        )

    with col2:
        confirm_master = st.checkbox("Confirm editing MASTER benchmark")
        # Show a warning if the checkbox is ticked but wrong type is selected
        if confirm_master and benchmark_type != "Master Office Benchmark":
            st.warning("⚠️ This checkbox is only relevant for Master Office Benchmarks.")

    # Conditional field — only enabled for non-master types
    benchmark_name = st.text_input(
        "Name Calculated Benchmark (Test / Custom / New Master only)",
        placeholder="e.g. Q1-2025-EMEA-Test",
        disabled=(benchmark_type == "Master Office Benchmark" and not confirm_master)
    )

    st.divider()

    # ── Years ──────────────────────────────────────────────────────────────────
    st.markdown('<p class="section-label">Select years for inclusion</p>',
                unsafe_allow_html=True)

    ALL_YEARS = [2020, 2021, 2022, 2023, 2024, 2025, 2026]

    select_all_years = st.checkbox("All years", key="chk_all_years")

    selected_years = st.multiselect(
        "Years",
        options=ALL_YEARS,
        default=ALL_YEARS if select_all_years else [2025],
        disabled=select_all_years,
        label_visibility="collapsed"
    )
    # Override selection if "All" is ticked
    if select_all_years:
        selected_years = ALL_YEARS

    st.divider()

    # ── Tenure ─────────────────────────────────────────────────────────────────
    st.markdown('<p class="section-label">Select Tenure</p>',
                unsafe_allow_html=True)

    ALL_TENURES = [
        "Freehold",
        "Long leasehold (> 30 years)",
        "Not Specified",
        "Other tenure type",
        "Serviced office",
        "Short leasehold (< 30 years)"
    ]

    select_all_tenure = st.checkbox("All tenures", key="chk_all_tenure")

    selected_tenure = st.multiselect(
        "Tenure types",
        options=ALL_TENURES,
        default=ALL_TENURES if select_all_tenure else [
            "Not Specified", "Other tenure type", "Serviced office"
        ],
        disabled=select_all_tenure,
        label_visibility="collapsed"
    )
    if select_all_tenure:
        selected_tenure = ALL_TENURES

    st.divider()

    # ── Property Predominant Use ───────────────────────────────────────────────
    st.markdown('<p class="section-label">Select Property predominant use</p>',
                unsafe_allow_html=True)

    ALL_PROPERTY_USES = [
        "Office", "Industrial", "Retail",
        "Residential", "Mixed Use", "Other", "Not Specified"
    ]

    select_all_use = st.checkbox("All use types", value=True, key="chk_all_use")

    selected_use = st.multiselect(
        "Property use types",
        options=ALL_PROPERTY_USES,
        default=ALL_PROPERTY_USES if select_all_use else [],
        disabled=select_all_use,
        label_visibility="collapsed"
    )
    if select_all_use:
        selected_use = ALL_PROPERTY_USES

    st.divider()

    # ── Geography ─────────────────────────────────────────────────────────────
    st.markdown('<p class="section-label">Geographic Filters</p>',
                unsafe_allow_html=True)

    col_country, col_city, col_building = st.columns(3)

    with col_country:
        selected_countries = st.multiselect(
            "Country",
            options=["UK", "Germany", "France", "Netherlands",
                     "Spain", "Italy", "USA"],
            default=["UK"]
        )

    with col_city:
        selected_cities = st.multiselect(
            "City",
            options=["London", "Manchester", "Berlin",
                     "Paris", "Amsterdam"]
        )

    with col_building:
        selected_buildings = st.multiselect(
            "Buildings",
            options=["Building A", "Building B", "Building C"]
        )

    st.divider()

    # ── KPIs ──────────────────────────────────────────────────────────────────
    st.markdown('<p class="section-label">Select KPIs</p>',
                unsafe_allow_html=True)

    ALL_KPIS = [
        "Total Occupancy Cost", "Cost per sqft", "Cost per desk",
        "Utilisation Rate", "Energy Consumption", "Carbon Emissions"
    ]

    selected_kpis = st.multiselect(
        "KPIs to include in the benchmark",
        options=ALL_KPIS,
        default=["Total Occupancy Cost", "Cost per sqft"]
    )


# ── Exclude Tab ───────────────────────────────────────────────────────────────
with tab_exclude:
    st.markdown('<p class="section-label">Exclude specific records</p>',
                unsafe_allow_html=True)
    exclude_buildings = st.multiselect(
        "Exclude buildings",
        options=["Building A", "Building B", "Building C"]
    )
    exclude_years = st.multiselect(
        "Exclude years",
        options=[2020, 2021, 2022, 2023, 2024, 2025, 2026]
    )


# ── Export Tab ────────────────────────────────────────────────────────────────
with tab_export:
    st.markdown('<p class="section-label">Configure output</p>',
                unsafe_allow_html=True)
    export_format = st.radio(
        "Export Format",
        options=["Excel (.xlsx)", "CSV", "Delta Table"],
        horizontal=True
    )
    export_path = st.text_input(
        "Output path / Delta table name",
        value="sandbox.benchmark_output"
    )
```

### 4.4 Run Workflow Button & Job Trigger

```python
st.divider()
col_btn, col_info = st.columns([1, 3])

with col_btn:
    run_clicked = st.button(
        "▶ Run Workflow",
        type="primary",
        use_container_width=True
    )

if run_clicked:

    # ── Input Validation ──────────────────────────────────────────────────────
    errors = []

    if not benchmark_name.strip() and benchmark_type != "Master Office Benchmark":
        errors.append("Benchmark Name is required for Test / Custom benchmarks.")

    if not selected_years:
        errors.append("Please select at least one year.")

    if not selected_kpis:
        errors.append("Please select at least one KPI.")

    if errors:
        for e in errors:
            st.error(f"❌ {e}")
        st.stop()

    # ── Build the job_parameters dict ─────────────────────────────────────────
    # All list values are JSON-serialised to strings because the Jobs API
    # only accepts string values in job_parameters.
    job_params = {
        "benchmark_type":  benchmark_type,
        "benchmark_name":  benchmark_name.strip(),
        "years":           json.dumps(selected_years),
        "tenure":          json.dumps(selected_tenure),
        "property_use":    json.dumps(selected_use),
        "countries":       json.dumps(selected_countries),
        "cities":          json.dumps(selected_cities),
        "buildings":       json.dumps(selected_buildings),
        "kpis":            json.dumps(selected_kpis),
        "export_format":   export_format,
        "export_path":     export_path,
        "confirm_master":  str(confirm_master).lower(),
    }

    # ── Trigger the Databricks Job ────────────────────────────────────────────
    JOB_ID = 123456789    # ← REPLACE with your actual Job ID

    with st.spinner("Triggering Databricks job..."):
        try:
            # WorkspaceClient() automatically uses the current user's
            # identity when running inside Databricks Apps — no credentials needed.
            w = WorkspaceClient()

            run = w.jobs.run_now(
                job_id=JOB_ID,
                job_parameters=job_params
            )

            run_id = run.response.run_id

            st.success(f"✅ Job triggered successfully!")

            col_id, col_link = st.columns(2)
            with col_id:
                st.metric("Run ID", run_id)
            with col_link:
                run_url = f"{w.config.host}#job/{JOB_ID}/run/{run_id}"
                st.markdown(f"[🔗 View this run in Databricks]({run_url})")

            # Save run_id so the status section below can use it
            st.session_state["last_run_id"] = run_id
            st.session_state["last_job_id"]  = JOB_ID
            st.session_state["last_params"]  = job_params

        except Exception as e:
            st.error(f"❌ Job trigger failed: {str(e)}")
```

### 4.5 Status Polling

```python
# ── Status Section — shown after a job has been triggered ────────────────────
if "last_run_id" in st.session_state:

    st.divider()
    st.markdown("### 🔄 Run Status")

    col_status, col_params = st.columns([1, 2])

    with col_status:
        if st.button("🔄 Refresh Status"):
            try:
                w = WorkspaceClient()
                run_details = w.jobs.get_run(
                    run_id=st.session_state["last_run_id"]
                )

                lifecycle = run_details.state.life_cycle_state.value
                result    = (run_details.state.result_state.value
                             if run_details.state.result_state else "—")

                STATUS_ICONS = {
                    "PENDING":        "🟡 Pending",
                    "RUNNING":        "🔵 Running",
                    "TERMINATED":     "🟢 Completed" if result == "SUCCESS" else "🔴 Failed",
                    "INTERNAL_ERROR": "🔴 Internal Error",
                    "SKIPPED":        "⚪ Skipped",
                }

                st.metric("Lifecycle State", STATUS_ICONS.get(lifecycle, lifecycle))
                st.metric("Result",          result)

            except Exception as e:
                st.error(f"Could not fetch status: {e}")

    with col_params:
        with st.expander("📋 Parameters sent to this run", expanded=False):
            st.json(st.session_state.get("last_params", {}))
```

---

## 5. app.yaml — Databricks App Configuration

Create `app.yaml` in the same folder as `app.py`. This tells Databricks how to run your app.

```yaml
command:
  - streamlit
  - run
  - app.py
  - --server.port=8080
  - --server.address=0.0.0.0
  - --server.headless=true

env:
  - name: STREAMLIT_SERVER_ENABLE_CORS
    value: "false"
  - name: STREAMLIT_SERVER_ENABLE_XSRF_PROTECTION
    value: "false"
```

> **Why `headless=true`?** Streamlit normally tries to open a browser tab when launched. On Databricks Apps, there's no desktop, so this flag suppresses that behaviour.

---

## 6. requirements.txt

```txt
streamlit>=1.35.0
databricks-sdk>=0.25.0
```

> Both packages are typically pre-installed in the Databricks Apps runtime. Include this file anyway — it makes the dependencies explicit and ensures the correct versions are used.

---

## 7. Deploying to Databricks Apps

### 7.1 Via Databricks UI

1. In your Databricks workspace, go to the left sidebar → **Apps**  
   *(If you don't see it, ask your admin to enable the Databricks Apps feature)*
2. Click **Create App**
3. Select **Custom** (not a template)
4. Give it a name: `benchmark-calculation-app`
5. Under **Source**, choose **Upload files** or point to a Databricks Repo/Git folder
6. Upload `app.py`, `app.yaml`, and `requirements.txt`
7. Click **Deploy**
8. Once deployed, you'll get a URL like:  
   `https://benchmark-calculation-app-xxxx.databricksapps.com`

### 7.2 Via Databricks CLI

**Step 1 — Install and configure the CLI:**
```bash
pip install databricks-cli
databricks configure --token
# Enter your workspace URL and personal access token when prompted
```

**Step 2 — Deploy the app:**
```bash
# Navigate to your project folder
cd benchmark-app/

# Deploy the app (creates it if it doesn't exist, updates if it does)
databricks apps deploy benchmark-calculation-app \
  --source-code-path .
```

**Step 3 — Check deployment status:**
```bash
databricks apps get benchmark-calculation-app
```

**Step 4 — Get the URL:**
```bash
databricks apps get benchmark-calculation-app --output json | python3 -c \
  "import sys, json; print(json.load(sys.stdin)['url'])"
```

---

## 8. How Parameters Reach the Notebook

This is the end-to-end flow of a single filter selection:

```
Stakeholder selects:
  Years → [2025, 2026]
  Tenure → ["Not Specified", "Serviced office"]
  KPIs → ["Cost per sqft"]

                    ↓

Streamlit serialises to strings:
  job_params = {
      "years":   "[2025, 2026]",
      "tenure":  "[\"Not Specified\", \"Serviced office\"]",
      "kpis":    "[\"Cost per sqft\"]"
  }

                    ↓

Databricks SDK call:
  w.jobs.run_now(job_id=123456789, job_parameters=job_params)

                    ↓

Databricks Jobs API receives:
  POST /api/2.1/jobs/run-now
  {
    "job_id": 123456789,
    "job_parameters": {
      "years": "[2025, 2026]",
      "tenure": "[\"Not Specified\", \"Serviced office\"]",
      "kpis": "[\"Cost per sqft\"]"
    }
  }

                    ↓

Notebook reads and deserialises:
  years  = json.loads(dbutils.widgets.get("years"))   → [2025, 2026]
  tenure = json.loads(dbutils.widgets.get("tenure"))  → ["Not Specified", "Serviced office"]
  kpis   = json.loads(dbutils.widgets.get("kpis"))    → ["Cost per sqft"]

                    ↓

Notebook uses values in business logic:
  df_filtered = df.filter(df.year.isin(years))
  df_filtered = df_filtered.filter(df_filtered.tenure.isin(tenure))
```

---

## 9. Granting Stakeholder Access

Once the app is deployed, stakeholders need access.

**Step 1 — Grant workspace access (if they don't have it):**
1. Go to **Settings → Identity and access → Users**
2. Add the stakeholder's email
3. Assign role: **User** (not Admin)

**Step 2 — Grant app access:**
1. Go to **Apps → benchmark-calculation-app → Permissions**
2. Add the stakeholder or their group
3. Assign: **Can Use**

**Step 3 — Grant job run permission:**
1. Go to **Workflows → Your Job → Permissions**
2. Add the stakeholder (or the app's service identity)
3. Assign: **Can Manage Run**

**Step 4 — Share the URL:**  
Send stakeholders the app URL. They log in with their Databricks credentials and land directly on the filter form. No additional tooling or installation required.

---

## 10. Testing Checklist

Run through this before handing over to stakeholders:

### Functionality
- [ ] App loads without errors
- [ ] "All years" checkbox selects all years and disables individual checkboxes
- [ ] "All tenures" checkbox works the same way
- [ ] "All use types" checkbox (defaulted to true) works correctly
- [ ] Benchmark Name field is disabled when Master Office Benchmark is selected (without confirm checkbox)
- [ ] Clicking Run without a Benchmark Name shows a validation error
- [ ] Clicking Run with no years selected shows a validation error
- [ ] Clicking Run with valid inputs triggers the job and returns a Run ID
- [ ] The Databricks run link in the success message opens the correct run
- [ ] "Refresh Status" button shows the current lifecycle state
- [ ] Parameters expander shows the exact values that were sent

### Notebook
- [ ] Notebook `print()` statements confirm correct values were received
- [ ] `json.loads()` on list parameters produces actual lists (not strings)
- [ ] Notebook completes successfully end-to-end with test inputs

### Access
- [ ] A stakeholder (non-admin) account can access the app URL
- [ ] A stakeholder can trigger a job run successfully
- [ ] A stakeholder cannot access the Databricks notebook directly (permissions check)

---

## 11. Troubleshooting

### App fails to start — `ModuleNotFoundError: No module named 'databricks'`
**Cause:** `databricks-sdk` not installed in the app's environment.  
**Fix:** Ensure `requirements.txt` includes `databricks-sdk>=0.25.0` and redeploy.

---

### `PermissionDenied` when triggering the job
**Cause:** The logged-in user (or the app's identity) does not have `Can Manage Run` on the job.  
**Fix:** Go to Workflows → Job → Permissions → add the user/group with `Can Manage Run`.

---

### `json.JSONDecodeError` in the notebook
**Cause:** The notebook is calling `json.loads()` on a parameter that was not JSON-serialised by the app — e.g., `benchmark_type` which is a plain string.  
**Fix:** Only use `json.loads()` on parameters that were serialised with `json.dumps()` (the list parameters). String parameters like `benchmark_type` and `benchmark_name` should be read directly with `dbutils.widgets.get()`.

---

### Streamlit page rerenders and resets the form when clicking Run
**Cause:** Normal Streamlit behaviour — the script reruns on every interaction.  
**Fix:** Use `st.session_state` to persist the `run_id` and any other values that should survive rerenders. This is already implemented in the code above.

---

### `WorkspaceClient()` fails with `AuthError` when running locally
**Cause:** Outside Databricks Apps, there is no automatic auth context.  
**Fix:** Set environment variables before running locally:
```bash
export DATABRICKS_HOST=https://adb-xxxx.azuredatabricks.net
export DATABRICKS_TOKEN=dapi_your_pat_token_here
streamlit run app.py
```

---

### App URL gives a 403 Forbidden to a stakeholder
**Cause:** The stakeholder's account does not have `Can Use` permission on the app.  
**Fix:** Go to Apps → benchmark-calculation-app → Permissions → add the stakeholder.

---

*End of guide.*
