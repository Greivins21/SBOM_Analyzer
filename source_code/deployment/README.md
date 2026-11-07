# App Deployment & HTTPS Configuration Guide

This guide describes how to deploy the Dependency Reader application on a new machine and configure secure HTTPS access using **DuckDNS**, **Let's Encrypt**, and **Nginx** directly within Docker Compose.

---

## How It Works (The Tech Stack)

When you deploy this application, several components work together automatically to make the connection secure:

1. **DuckDNS (Dynamic DNS)**
   - Normal IP addresses (like `123.45.67.89`) are hard to remember. DuckDNS gives you a free subdomain (like `yourhost.duckdns.org`) that points to your machine's public IP address.
   
2. **HTTPS & SSL Certificate**
   - HTTPS encrypts all communication between the user's browser and your server, making sure no one can spy on or tamper with the data.
   - To enable HTTPS, you need a trusted SSL certificate. **Let's Encrypt** provides these certificate files for free.
   
3. **Certbot (Integrated in Docker Compose)**
   - Certbot is the client tool used to request certificates from Let's Encrypt.
   - To prove you own the domain, Let's Encrypt requires a DNS validation test (the `dns-01` challenge). Instead of doing this manually, Certbot runs inside its own Docker Compose container and automatically updates your DuckDNS settings.
   - Once Let's Encrypt verifies the DNS settings, it issues the certificates and saves them to a shared directory.
   
4. **Nginx (Reverse Proxy)**
   - Nginx is the web server facing the public internet. It listens for incoming HTTP (port `80`) and HTTPS (port `443`) requests.
   - Nginx automatically redirects any unsecured HTTP requests to secure HTTPS.
   - Nginx uses your Let's Encrypt certificates to secure the connection, decrypts the request, and proxies (forwards) it internally to the frontend (Flask) or backend (FastAPI) Docker services.

---

## The DuckDNS Verification Commands Explained

We need to update DuckDNS records during Let's Encrypt verification. The `certbot` service inside `docker-compose.yml` runs these validation and cleanup commands inline:

### 1. Verification Hook (Authentication)
When Certbot requests a certificate, Let's Encrypt gives it a temporary verification token (stored in the `$CERTBOT_VALIDATION` variable). Certbot uses `curl` to update your DuckDNS domain text (`TXT`) record with this value:
```bash
curl -s "https://www.duckdns.org/update?domains=<YOUR_SUBDOMAIN>&token=<YOUR_DUCKDNS_TOKEN>&txt=<CERTBOT_VALIDATION_TOKEN>"
```
*After this command runs, Certbot pauses for 30 seconds to allow the DNS record changes to propagate worldwide so Let's Encrypt can verify it.*

### 2. Cleanup Hook
Once Let's Encrypt successfully reads the TXT record and issues the certificates, Certbot runs a second command to clear the TXT record to keep it clean:
```bash
curl -s "https://www.duckdns.org/update?domains=<YOUR_SUBDOMAIN>&token=<YOUR_DUCKDNS_TOKEN>&txt=&clear=true"
```

---

## Prerequisites

Before starting, make sure the target machine has:
- **Docker** and **Docker Compose** installed.
- Ports **80** and **443** free and open to the internet.
- A **DuckDNS account** with a registered subdomain and your API Token.

---

## Step-by-Step Deployment Instructions

### Step 1: Clone the Repository
Copy the entire `micac_soa_2026_sh` project folder to the target machine.

### Step 2: Configure Environment Variables
In the root of the project, create or update the `.env` file (located two levels up from this folder):

```env
GITHUB_TOKEN=your_github_token_here
ALLOWED_ORIGINS=https://your-subdomain.duckdns.org:14361
DUCKDNS_TOKEN=your_duckdns_token_here
DOMAIN=your-subdomain.duckdns.org
EMAIL=your-email@example.com
```
*Note: Make sure to replace `your-subdomain.duckdns.org`, `your_duckdns_token_here`, and `your-email@example.com` with your actual information.*

### Step 3: Update the Nginx Configuration
Ensure the domain name in `source_code/deployment/nginx.conf` matches your domain. Open the file and update the following lines if they don't match:

- **Line 3 & 11:** Update `server_name` to your domain:
  ```nginx
  server_name your-subdomain.duckdns.org;
  ```
- **Line 13 & 14:** Update the certificate path folder names to match your domain name:
  ```nginx
  ssl_certificate /etc/nginx/certs/live/your-subdomain.duckdns.org/fullchain.pem;
  ssl_certificate_key /etc/nginx/certs/live/your-subdomain.duckdns.org/privkey.pem;
  ```

### Step 4: Start the Docker Compose Stack
Deploy the services in the background using Docker Compose:

```bash
docker compose up --build -d
```

### What happens when you run this command:
1. Docker Compose builds the frontend and backend services.
2. The `certbot` container starts up, automatically runs the inline validation/cleanup `curl` commands to obtain your Let's Encrypt SSL certificates, and stores them in `./certs`.
3. Once the `certbot` service completes successfully, the `nginx` container starts up automatically, loads the new certificates, and begins serving secure traffic.

---

## Step 5: Access the Application
The application is now running securely under HTTPS:
- **Frontend (Website):** `https://your-subdomain.duckdns.org:14361` (or your configured port mapping)
- **Backend API Docs:** `https://your-subdomain.duckdns.org:14361/api/docs`

---

## Benchmarking Commands

Test it with 30 people at the same time 
```bash
torres in ~                                                                    13s  10:55:29
❯ seq 1 30 | xargs -I {} -P 30 curl -s -o /dev/null -w "User {}: HTTP %{http_code} (took %{time_total}s)\n" \
  -X POST https://ship-happens.duckdns.org:14361/api/zombie-scan \
  -H "Content-Type: application/json" \
  -d '{"repo_url": "https://github.com/boto/boto3"}'
User 6: HTTP 200 (took 11.398266s)
User 29: HTTP 200 (took 11.550966s)
User 19: HTTP 200 (took 12.084509s)
User 7: HTTP 200 (took 12.164908s)
User 8: HTTP 200 (took 12.350183s)
User 24: HTTP 200 (took 12.503482s)
User 16: HTTP 200 (took 12.580276s)
User 4: HTTP 200 (took 12.706819s)
User 1: HTTP 200 (took 12.841257s)
User 17: HTTP 200 (took 12.876592s)
User 26: HTTP 200 (took 13.275114s)
User 10: HTTP 200 (took 13.322581s)
User 12: HTTP 200 (took 13.384708s)
User 20: HTTP 200 (took 13.375558s)
User 25: HTTP 200 (took 13.383529s)
User 21: HTTP 200 (took 13.469417s)
User 23: HTTP 200 (took 13.487115s)
User 14: HTTP 200 (took 13.508351s)
User 15: HTTP 200 (took 13.545263s)
User 18: HTTP 200 (took 13.663789s)
User 30: HTTP 200 (took 13.663449s)
User 13: HTTP 200 (took 13.702396s)
User 11: HTTP 200 (took 13.709467s)
User 3: HTTP 200 (took 13.735153s)
User 2: HTTP 200 (took 13.741392s)
User 27: HTTP 200 (took 13.722346s)
User 9: HTTP 200 (took 13.781607s)
User 28: HTTP 200 (took 13.850546s)
User 22: HTTP 200 (took 16.347667s)
User 5: HTTP 200 (took 16.373052s)
```

## Helpful Operations Commands

- **Check Logs:**
  ```bash
  docker compose logs -f
  ```
- **Stop the Stack:**
  ```bash
  docker compose down
  ```
- **Rebuild Services (after code changes):**
  ```bash
  docker compose up --build -d
  ```
