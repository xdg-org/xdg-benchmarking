# XDG Benchmarking Dashboard - Deployment Guide

This guide provides several options for deploying your dynamic Dash dashboard while maintaining full functionality.

## Option 1: Render.com (Recommended - Free Tier)

Render.com offers free hosting for web services with automatic GitHub deployments.

### Setup Steps:

1. **Fork/Clone your repository** to ensure you have the latest code
2. **Sign up at [render.com](https://render.com)**
3. **Connect your GitHub account**
4. **Create a new Web Service**:
   - Connect your repository
   - Set **Build Command**: `pip install -r requirements.txt`
   - Set **Start Command**: `gunicorn app:server`
   - Set `XDG_RESULTS_ZIP_URL` to the direct benchmark ZIP download URL
     (see [remote results configuration](README.md#fetching-remote-results))
   - Set **Environment**: Python 3
5. **Deploy** - Render will automatically build and deploy your app

### Benefits:
- ✅ Free tier available
- ✅ Automatic deployments from GitHub
- ✅ Custom domain support
- ✅ SSL certificates included
- ✅ Full dynamic functionality preserved

---

## Option 2: Railway.app (Alternative Free Option)

Railway offers similar functionality to Render with a generous free tier.

### Setup Steps:

1. **Sign up at [railway.app](https://railway.app)**
2. **Connect your GitHub repository**
3. **Create a new service** from your repository
4. **Railway will auto-detect** it's a Python app
5. **Deploy** - Railway handles the rest automatically

### Benefits:
- ✅ Free tier available
- ✅ Automatic deployments
- ✅ Built-in monitoring
- ✅ Easy scaling

---

## Option 3: Heroku (Paid but Reliable)

Heroku is a mature platform with excellent Dash support.

### Setup Steps:

1. **Install Heroku CLI**
2. **Create a `Procfile`**:
   ```
   web: gunicorn app:server
   ```
3. **Deploy**:
   ```bash
   heroku create your-app-name
   git push heroku main
   ```

### Benefits:
- ✅ Excellent Dash support
- ✅ Reliable and mature platform
- ✅ Good documentation
- ⚠️ No free tier (paid plans start at $7/month)

---

## Option 4: DigitalOcean App Platform

DigitalOcean's App Platform is great for containerized applications.

### Setup Steps:

1. **Sign up at [digitalocean.com](https://digitalocean.com)**
2. **Create a new App**
3. **Connect your GitHub repository**
4. **Configure the app**:
   - Build Command: `pip install -r requirements.txt`
   - Run Command: `gunicorn app:server`
5. **Deploy**

### Benefits:
- ✅ Good performance
- ✅ Reasonable pricing
- ✅ Easy scaling
- ⚠️ No free tier

---

## Option 5: Self-Hosted with Docker

For complete control, you can self-host using Docker.

### Setup Steps:

1. **Build the Docker image**:
   ```bash
   docker build -t xdg-dashboard .
   ```

2. **Run the container**:
   ```bash
   docker run -p 8050:8050 xdg-dashboard
   ```

3. **For production**, use Docker Compose:
   ```yaml
   version: '3.8'
   services:
     dashboard:
       build: .
       ports:
         - "8050:8050"
       volumes:
         - ./results:/app/results
   ```

### Benefits:
- ✅ Complete control
- ✅ No hosting costs
- ✅ Can run anywhere
- ⚠️ Requires server management

---

## Option 6: Hybrid Approach (Static + Dynamic)

If you want to keep GitHub Pages for static content but add dynamic functionality:

### Setup:

1. **Keep your static dashboard** in the `docs/` folder for GitHub Pages
2. **Deploy the dynamic version** to Render/Railway
3. **Add a link** in your static site to the dynamic version
4. **Use the static version** as a fallback when the dynamic server is down

### Benefits:
- ✅ Always have a working version (static)
- ✅ Dynamic functionality when available
- ✅ No downtime
- ✅ SEO benefits from static content

---

## Recommended Approach

**For your use case, I recommend Option 1 (Render.com)** because:

1. **Free tier** is generous
2. **Automatic deployments** from GitHub
3. **Full dynamic functionality** preserved
4. **Easy setup** and maintenance
5. **Good performance** for dashboards

## Migration Steps

1. **Choose your hosting platform** (Render recommended)
2. **Follow the setup steps** above
3. **Test the deployment** thoroughly
4. **Update your documentation** with the new URL
5. **Consider keeping the static version** as a backup

## Environment Variables

If you need to configure environment variables, add them in your hosting platform's dashboard:

- `DEBUG=False` (for production)
- Any API keys or configuration values

## Monitoring

Most platforms provide built-in monitoring. For additional monitoring, consider:

- **Uptime monitoring**: UptimeRobot (free)
- **Error tracking**: Sentry (free tier available)
- **Analytics**: Google Analytics

## Cost Comparison

| Platform | Free Tier | Paid Plans | Best For |
|----------|-----------|------------|----------|
| Render.com | ✅ Yes | $7+/month | Most users |
| Railway.app | ✅ Yes | $5+/month | Alternative to Render |
| Heroku | ❌ No | $7+/month | Enterprise users |
| DigitalOcean | ❌ No | $5+/month | Performance-focused |
| Self-hosted | ✅ Yes | Server costs | Complete control |

Choose based on your budget and technical requirements!
