# Going live: deploying the dashboard online

The app is a standard Flask app with a `Procfile` and `gunicorn` already set
up, so it deploys to any Python host in a few minutes. Below is the easiest
free path (Render). Railway, Fly.io, or PythonAnywhere work the same way.

## ⚠️ Read this first: the database

This app stores everything in a local SQLite file. By default that's
`instance/accomplishment.db`, which is fine for local use — but on most free
hosting platforms (including Render's free tier) **the disk is wiped every
time the app restarts or redeploys**, so you'd lose all employees, outputs,
schedules, tickets, **and every user account you created** (see the Accounts
section below — accounts live in this same database file).

This version adds an `INSTANCE_DIR` environment variable so you don't need
any code changes to fix this:

1. **Add a persistent disk** on your host (Render's "Starter" plan, Railway
   volumes, Fly.io volumes, etc.) and mount it at, say, `/data`.
2. Set the environment variable `INSTANCE_DIR=/data` (or `DATABASE_PATH` if
   you only want to move the database file and keep reports/uploads local).
3. Redeploy. The app will now read/write the database, generated reports,
   and uploaded logo from the persistent disk instead of the ephemeral one.

If this is for testing/demoing first, skip this step — just know a redeploy
will reset your data, including any accounts and messages.

We've also switched the database to SQLite's **WAL journal mode**, which
fixes the "database is locked" errors that can otherwise show up once the
app is deployed behind gunicorn with more than one worker process reading
and writing the same file at the same time.

## Accounts, roles, and login

Login is now per-user instead of one shared password:

- `APP_USERNAME` / `APP_PASSWORD` (below) only matter **once** — the very
  first time the app starts against an empty database, it creates a single
  Administrator account from those two values and never reads them again
  after that. Changing `APP_PASSWORD` later and redeploying does **not**
  reset that account's password (since it already exists in the database) —
  update the password from the in-app **Users** page instead, or delete
  `instance/accomplishment.db` to force reseeding (only do this if you're
  fine losing all existing data).
- Once you've logged in as that Administrator, go to **Users** in the
  sidebar to create real accounts for your team and assign each one a role:
  **Administrator**, **Information Systems Analyst I**, or **User**.
  - Information Systems Analyst I / Administrator accounts can change a
    ticket's status and are the only ones the reporting user's ticket
    thread and progress bar are meant for.
  - User accounts can log tickets, message the assigned analyst on their
    own tickets, and use the general 1-on-1 messenger with anyone.
- The 1-on-1 messenger (**Messages**) auto-deletes messages 10 hours after
  they're sent — this happens inside the app itself (no extra cron job or
  background worker to configure on your host).

## Deploy to Render (free, no credit card)

1. Push this project to a GitHub repository (create one if you don't have
   one yet — `git init`, `git add .`, `git commit -m "Initial commit"`,
   then push to GitHub).
2. Go to [render.com](https://render.com) and sign up / log in.
3. Click **New +** → **Web Service** → connect your GitHub repo.
4. Fill in:
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn wsgi:app`
5. Under **Environment**, add these variables:
   - `FLASK_ENV` = `production`
   - `SECRET_KEY` = (paste the output of
     `python -c "import secrets; print(secrets.token_hex(32))"`)
   - `APP_USERNAME` = the username for the first (Administrator) account —
     only used the very first time the app starts, see Accounts above
   - `APP_PASSWORD` = a strong password for that first account
   - `INSTANCE_DIR` = the mount path of your persistent disk (e.g. `/data`),
     if you attached one — see the database note above. Skip this if you're
     just testing/demoing.
6. Click **Create Web Service**. Render builds and deploys automatically —
   you'll get a live URL like `https://your-app.onrender.com`.
7. If you attached a persistent disk, mount it and set `INSTANCE_DIR` to
   that mount path (step 5) — no further code changes needed.
8. Log in with the Administrator account, then immediately go to **Users**
   and create named accounts (with the correct role) for everyone on your
   team instead of sharing the Administrator login.

Every future `git push` to your connected branch redeploys automatically.

## Custom domain

Once live, Render (or Railway/Fly) lets you attach your own domain under
**Settings → Custom Domains** — just add a CNAME record at your domain
registrar pointing to the URL Render gives you.

## Before you make the link public

- [ ] Change `APP_PASSWORD` from the default **before the first deploy**
      (it only takes effect when the database is empty — see Accounts
      above).
- [ ] Set a real `SECRET_KEY` (not the placeholder).
- [ ] Attach a persistent disk and set `INSTANCE_DIR` (see above), unless
      this is just a demo/test deploy — otherwise every account you create
      is lost on the next redeploy.
- [ ] Log in as Administrator and create a named account (with the right
      role) for each real team member instead of sharing one login.
- [ ] Test creating an employee, logging outputs, logging a ticket, and
      downloading a DAR on the live URL before sharing it with your team.
