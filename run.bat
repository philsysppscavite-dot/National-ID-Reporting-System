# Connecting Users + the NID Concern Matrix to Google Sheets

Users, NID Concerns, and their concern message threads now live in a Google
Sheet instead of the local database. (Employees, Outputs, Schedules,
Signatories, and Import Sources stay on the app's regular database — they
rely on SQL joins/aggregation for reporting that a spreadsheet can't do
efficiently. The 1-on-1 Messenger also stays where it is, since it needs to
be fast and auto-delete on a timer.)

Your sheet: https://docs.google.com/spreadsheets/d/1C0tDol4AQL59ODPbsADUVEZaGwlB7DAPwE8Fwgi4Lxs/edit

The app will automatically create 3 tabs in it the first time it starts up
— **Users**, **NidConcerns**, **ConcernMessages** — each with its header
row already filled in. You don't need to create anything by hand.

## 1. Create a Google Cloud service account

A service account is a robot identity your app uses to talk to the Sheets
API — this is separate from your personal Google login.

1. Go to https://console.cloud.google.com/ and create a project (or use an
   existing one).
2. Go to **APIs & Services → Library**, search for **Google Sheets API**,
   and click **Enable**.
3. Go to **APIs & Services → Credentials → Create Credentials → Service
   account**. Give it any name (e.g. `nid-reporting-sheets`).
4. Open the service account you just created → **Keys** tab → **Add Key →
   Create new key → JSON**. This downloads a `.json` file — keep it
   private, it's effectively a password.

## 2. Share your Google Sheet with the service account

1. Open the downloaded JSON file and copy the value of `"client_email"`
   (it looks like `nid-reporting-sheets@your-project.iam.gserviceaccount.com`).
2. Open your Google Sheet → **Share** → paste that email → give it
   **Editor** access → Send.

Without this step the app can authenticate but won't be able to see or
write to your specific sheet.

## 3. Set environment variables on Render

In your Render service → **Environment**, add:

| Key | Value |
|---|---|
| `GOOGLE_SHEETS_CREDENTIALS_JSON` | The **entire contents** of the JSON key file, pasted as one line |
| `GOOGLE_SHEET_ID` | `1C0tDol4AQL59ODPbsADUVEZaGwlB7DAPwE8Fwgi4Lxs` (already the default if you skip this, but explicit is safer) |

To turn the JSON file into "one line" for pasting into Render's env var
box, you can open it in a text editor — it's already valid as a single
JSON value even across multiple lines, most env var UIs (including
Render's) accept multi-line values pasted directly into the value field.

(Local/alternate option: instead of pasting the JSON, you can set
`GOOGLE_SHEETS_CREDENTIALS_FILE` to a file path on disk if you'd rather
mount the key as a file than an env var.)

## 4. Deploy

Push this code to your repo and deploy as usual. On first boot the app
will:
- Create the `Users`, `NidConcerns`, and `ConcernMessages` tabs (with
  headers) if they don't exist yet.
- Seed one starter Administrator account into the `Users` tab (from your
  existing `APP_USERNAME` / `APP_PASSWORD` env vars, same as before) if
  the Users tab is empty.

After that, registering users and logging NID concerns writes directly
into your Google Sheet — you (or anyone with view access to the sheet)
can watch rows appear in real time, and can also read the data directly
from Sheets for your own ad-hoc reporting.

## Notes

- **Never delete rows by hand carelessly** — the app tracks each user/
  ticket by the number in the `id` column. If you manually delete a row
  from the middle of the sheet, that's fine; if you edit `id` values,
  things will break.
- The app disables a user by setting `active` to `0` on the **Users**
  page (Edit → uncheck Active) rather than deleting the row — this is
  also reflected directly in the sheet.
- A short (~20 second) in-memory cache means a change made directly in
  the sheet by a person (not through the app) may take up to ~20 seconds
  to show up in the app.
