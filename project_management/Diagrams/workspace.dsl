workspace "Ship Happens" "Zombie Package Detector for GitHub repos." {

    model {

        developer     = person "Developer" "Submits a GitHub repo URL."

        githubApi     = softwareSystem "GitHub API" "Repo metadata, commits, contributors." "External System"
        osvApi        = softwareSystem "OSV API" "Known CVEs per package." "External System"
        pkgRegistries = softwareSystem "Package Registries" "PyPI / npm / crates.io" "External System"

        shipHappens = softwareSystem "Ship Happens" "Scans dependencies. Returns a risk score: Safe / Warning / Dangerous." {

            nginx = container "Nginx" "Reverse proxy on port 80." "Nginx" "Infrastructure"

            webApp = container "Web App" "User interface. Enter a repo URL, see the report." "Flask + Gunicorn" "Web Browser" {
                ui      = component "HTML + JS Page" "Form to submit a repo URL." "HTML / JS"
                routes  = component "Flask Routes" "GET / — serve page. POST /analyze — forward to Scanner API." "Flask"
            }

            scannerApi = container "Scanner API" "Runs the analysis pipeline." "FastAPI + Uvicorn" {
                router   = component "Router" "POST /scan  POST /zombie-scan  GET /report" "FastAPI"
                utils    = component "Utils" "Fetch repo file tree. Parse dependency file." "Python"
                vuln     = component "Vuln Checker" "Check each package against OSV for CVEs." "Python"
                vitality = component "Vitality Enricher" "Days since last commit. Bus factor. Open issues." "Python"
                scorer   = component "Risk Scorer" "Score 0–100+ per package. Grade the whole repo." "Python"
            }
        }

        # Context
        developer    -> shipHappens  "Enter repo URL, get report"
        shipHappens  -> githubApi    "Fetch metadata & commit history"
        shipHappens  -> osvApi       "Check CVEs"
        shipHappens  -> pkgRegistries "Resolve package source URLs"

        # Containers
        developer  -> nginx      "HTTP :80"
        nginx      -> webApp     ":5000"
        nginx      -> scannerApi ":8000"
        webApp     -> scannerApi "POST /zombie-scan"
        scannerApi -> githubApi    "Commits, contributors, issues"
        scannerApi -> osvApi       "CVE lookup"
        scannerApi -> pkgRegistries "Package metadata"

        # Web App components
        developer -> ui     "Opens browser"
        ui        -> routes "POST /analyze"
        routes    -> scannerApi "POST /zombie-scan"

        # Scanner API pipeline
        router   -> utils    "1. Fetch & parse deps"
        utils    -> githubApi "GET repo contents"
        router   -> vuln     "2. Check CVEs"
        vuln     -> osvApi   "POST /v1/querybatch"
        router   -> vitality "3. Enrich vitality"
        vitality -> pkgRegistries "GET package info"
        vitality -> githubApi     "GET commits & issues"
        router   -> scorer   "4. Score & grade"
    }

    views {

        systemContext shipHappens "ProjectOverview" {
            include *
            autoLayout lr
            title "1. Project Overview"
            description "What the system does and who/what it talks to."
        }

        container shipHappens "WebInterfaceDiagram" {
            include *
            autoLayout lr
            title "2. Web Interface"
            description "Nginx, Web App, and Scanner API containers."
        }

        component scannerApi "APIFlowDiagram" {
            include *
            autoLayout lr
            title "3. API Flow — Analysis Pipeline"
            description "Four steps: parse deps → check CVEs → enrich vitality → score."
        }

        styles {
            element "Person" {
                shape Person
                background "#1B4F72"
                color "#ffffff"
            }
            element "Software System" {
                background "#2E86C1"
                color "#ffffff"
            }
            element "External System" {
                background "#717D7E"
                color "#ffffff"
            }
            element "Container" {
                background "#2874A6"
                color "#ffffff"
            }
            element "Infrastructure" {
                shape RoundedBox
                background "#5D6D7E"
                color "#ffffff"
            }
            element "Web Browser" {
                shape WebBrowser
                background "#1A5276"
                color "#ffffff"
            }
            element "Component" {
                background "#AED6F1"
                color "#1B2631"
            }
            relationship "Relationship" {
                dashed false
                color "#2E86C1"
            }
        }

        theme default
    }
}
