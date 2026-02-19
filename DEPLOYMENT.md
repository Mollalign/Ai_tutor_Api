# Deployment Guide - AI Study Tutor Backend

## Quick Start (Render)

### Prerequisites
- GitHub account with this repo pushed
- [Neon](https://neon.tech) PostgreSQL database (you already have this)
- [Upstash](https://upstash.com) Redis account (free tier)
- [Google AI Studio](https://aistudio.google.com/apikey) Gemini API key

### Step 1: Set Up Upstash Redis

1. Go to [upstash.com](https://upstash.com)
2. Create account → Create Database → Redis
3. Select region (closest to your users)
4. Copy the **Redis URL**: `redis://default:xxx@xxx.upstash.io:6379`

### Step 2: Deploy on Render

#### Option A: Blueprint (Recommended)
1. Push code to GitHub
2. Go to [render.com](https://render.com) → New → **Blueprint**
3. Connect your repository
4. Render reads `render.yaml` and creates services
5. Set secret environment variables (see below)

#### Option B: Manual Setup
1. Go to Render → New → **Web Service**
2. Connect GitHub repo
3. Configure:
   - **Name**: `ai-tutor-api`
   - **Runtime**: Python
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. Add environment variables
5. Repeat for **Background Worker** with start command: `arq app.worker.WorkerSettings`

### Step 3: Environment Variables

Set these in Render dashboard (Services → Environment):

| Variable | Value |
|----------|-------|
| `DATABASE_URL` | Your Neon PostgreSQL URL |
| `REDIS_URL` | Your Upstash Redis URL |
| `GEMINI_API_KEY` | Your Google Gemini API key |
| `SECRET_KEY` | Generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `DEBUG` | `false` |
| `FRONTEND_URL` | `https://mollalign.vercel.app` |
| `CORS_ORIGINS` | `["https://mollalign.vercel.app"]` |
| `EMBEDDING_DEVICE` | `cpu` |

### Step 4: Run Database Migrations

1. Go to your web service in Render
2. Click **Shell** tab
3. Run:
```bash
alembic upgrade head
```

### Step 5: Update Flutter App

Change API URL in your mobile app:

```dart
// lib/core/constants/api_constants.dart
static const String apiBaseUrl = 'https://ai-tutor-api.onrender.com/api/v1';
```

---

## Important Notes

### Cold Starts
- Render free tier sleeps after 15 min inactivity
- First request after sleep takes 30-60 seconds
- Subsequent requests are fast

### File Storage (Important!)
- Free tier has **ephemeral storage** - files are lost on redeploy
- For production, use Cloudflare R2 or Supabase Storage
- Set `STORAGE_BACKEND=s3` and configure S3-compatible credentials

### Memory Limits
- Free tier: 512MB RAM
- PyTorch + Sentence Transformers use ~1GB
- May need to upgrade to paid tier for production

### Free Tier Limits
- 750 hours/month (shared across all free services)
- If running web + worker 24/7, you'll hit the limit mid-month

---

## Monitoring

### Health Check
```
GET https://ai-tutor-api.onrender.com/health
```

Returns:
```json
{
  "status": "healthy",
  "database": "connected",
  "redis": "connected",
  "vector_store": "connected"
}
```

### Logs
View logs in Render Dashboard → Your Service → Logs tab

---

## Troubleshooting

### "Module not found" errors
- Ensure all dependencies are in `requirements.txt`
- Run `pip freeze > requirements.txt` locally

### Database connection errors
- Check `DATABASE_URL` format: `postgresql+asyncpg://user:pass@host/db`
- Ensure Neon database is not paused

### Redis connection errors
- Verify Upstash URL format
- Check if Upstash free tier limits are exceeded

### Out of memory
- Reduce `EMBEDDING_BATCH_SIZE` to 16
- Consider upgrading to paid tier

---

## Local Development

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

# Install dependencies
pip install -r requirements.txt

# Copy environment file
cp .env.example .env
# Edit .env with your values

# Run database migrations
alembic upgrade head

# Start the API
uvicorn app.main:app --reload --port 8000

# In another terminal, start the worker
arq app.worker.WorkerSettings
```
