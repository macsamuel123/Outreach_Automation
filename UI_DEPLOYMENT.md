# B2B Pipeline Dashboard - Deployment Guide

## Overview

This folder contains the React/Next.js frontend for the B2B prospecting pipeline dashboard.

## Architecture

- **Frontend**: Next.js + React on Vercel
- **Backend**: FastAPI on Railway (from `outreach_agent/api.py`)
- **Database**: Neon Postgres (shared with pipeline)
- **Auth**: GitHub OAuth

## Setup

### 1. Local Development

```bash
cd ui
npm install
npm run dev
```

Visit http://localhost:3000

### 2. Backend Setup (Railway)

1. Create a Railway account (free tier)
2. Create a new project, select "GitHub Repo"
3. Connect your Outreach_Automation repo
4. In Railway dashboard:
   - Add environment variables:
     - `GITHUB_CLIENT_ID` (from GitHub OAuth app)
     - `GITHUB_CLIENT_SECRET` (from GitHub OAuth app)
     - `GITHUB_TOKEN` (personal access token for workflow_dispatch)
     - `DATABASE_URL` (your Neon Postgres URL)
   - Set start command: `python -m outreach_agent.api`
   - Deploy

5. Get the Railway public URL (e.g., `https://xxxx.railway.app`)

### 3. Frontend Setup (Vercel)

1. Create a Vercel account
2. Import the GitHub repo
3. In Vercel dashboard:
   - Set root directory to `ui/`
   - Add environment variables:
     - `NEXT_PUBLIC_API_URL`: Your Railway backend URL
     - `NEXT_PUBLIC_GITHUB_CLIENT_ID`: Same as Railway
   - Deploy

### 4. GitHub OAuth App Setup

1. Go to GitHub Settings → Developer settings → OAuth Apps
2. Create a new OAuth App:
   - Application name: "B2B Pipeline Dashboard"
   - Homepage URL: Your Vercel URL (e.g., https://dashboard.vercel.app)
   - Authorization callback URL: `https://dashboard.vercel.app`
   - Copy Client ID and Client Secret
3. Store in Railway and Vercel environment variables

## Features

- **Dashboard**: Real-time metrics (discovered, qualified, verified, sent)
- **Partners**: Browse and edit partner records
- **Leads**: View discovered leads by status
- **Audit Log**: Search audit logs, export as CSV
- **Runs**: View pipeline run history and logs
- **Manual Trigger**: Trigger pipeline runs from the UI

## API Endpoints

See `outreach_agent/api.py` for full API documentation.

Key endpoints:
- `POST /auth/github/callback` - OAuth exchange
- `GET /api/stats` - Dashboard metrics
- `GET /api/partners` - List partners
- `PUT /api/partners/{id}` - Update partner
- `POST /api/runs/trigger` - Trigger pipeline run
- `GET /api/runs` - List runs
- `GET /api/audit-log` - Search audit logs

## Troubleshooting

### "API connection refused"
- Ensure `NEXT_PUBLIC_API_URL` is set to Railway backend URL
- Check Railway deployment is running
- Verify GitHub OAuth credentials

### "GitHub OAuth failed"
- Check Client ID and Client Secret are correct
- Verify callback URL matches in both GitHub and Vercel

### "Database connection failed"
- Verify `DATABASE_URL` is set in Railway
- Check Neon Postgres is running and accessible

## Development Tips

- API client is in `src/lib/api.ts`
- All pages fetch data on mount
- Token stored in `localStorage` as `github_token`
- Add new pages in `src/pages/`

## Deployment Checklist

- [ ] Railway backend deployed and running
- [ ] GitHub OAuth app created with correct credentials
- [ ] Environment variables set in Railway and Vercel
- [ ] Vercel frontend deployed
- [ ] Test GitHub login flow
- [ ] Test dashboard loads with real data
- [ ] Test editing partners works
- [ ] Test triggering a pipeline run
