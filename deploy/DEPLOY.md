# How to put PolicyC on the internet (complete beginner guide)

You do **not** need to understand the technology. Do the steps in order, tick each one off, and
check the "✅ You should see" line after every step. If what you see is different, jump to
**Part 9: When something goes wrong**.

* **Time:** about 1.5 to 2 hours, most of it waiting for builds.
* **Cost:** ₹0 / $0. You never enter a credit card. If any page asks for a card, stop: you are on
  the wrong page or the wrong plan.
* **Your computer:** Windows, with the project folder at
  `C:\abh_pers_od_tfr\google_ai_builder\Project_GCP_AI_Builder\policyc`

---

## The big picture (read once, 1 minute)

PolicyC has two halves. Think of a restaurant:

| Half | Restaurant | Where it will live | Free service |
|---|---|---|---|
| **Website** (what people see and click) | the dining room | **Firebase Hosting** (Google) | Firebase "Spark" plan |
| **Engine** (reads documents, finds bugs) | the kitchen | **Render** | Render "Free" web service |
| **Brain** (Gemini AI) | the head chef | Google | your **API key** |
| **Login** ("Sign in with Google") | the doorman | **Firebase Authentication** | free |
| **Code storage** | the recipe book | **GitHub** | free |

Render builds the engine from your code on GitHub. Firebase serves the website. They are told each
other's addresses.

### What the free engine can and cannot do

The free Render machine has only **512 MB of memory**, so the engine runs in **lightweight mode**.

| ✅ Works | ❌ Does not work |
|---|---|
| All nine sample procedures, instantly | Uploading **PDF, Word or HTML** files (they are refused with a clear message) |
| Flowchart, problems, animated traces, health score | |
| **Explain & fix → Apply & recompile** | |
| Uploading **.txt** or **.md** files and compiling them | |
| Sign in with Google, regression reports, export | |

**Free-tier behaviour to expect:** after 15 minutes without visitors the engine *falls asleep*; the
next visitor waits about a minute while it wakes up (Part 8 shows a free trick to keep it awake). Anything a visitor
uploads is forgotten when it restarts; the nine samples always come back.

### Words you will meet

| Word | Meaning in plain English |
|---|---|
| **API key** | A secret password that lets the engine talk to Gemini. **Never** post it anywhere public. |
| **Repository ("repo")** | A folder of code stored on GitHub. |
| **Commit / push** | Save a snapshot of your code / upload it to GitHub. |
| **Environment variable** | A setting on Render. Some are secret. |
| **Build / deploy** | Assembling and publishing. It takes a while. Normal. |
| **Terminal / PowerShell** | The blue text window where you type commands. |
| **Project ID** | The short unique name Firebase gives your project, like `policyc-12345`. |

### Write these down as you go

Open Notepad and paste this. You will fill it in. **Keep this file private.**

```
GEMINI KEY (secret):          ______________________________
FIREBASE PROJECT ID:          ______________________________
FIREBASE apiKey:              ______________________________
FIREBASE authDomain:          ______________________________
FIREBASE appId:               ______________________________
FIREBASE messagingSenderId:   ______________________________
GITHUB USERNAME:              ______________________________
GITHUB REPO URL:              https://github.com/__________/policyc
ENGINE ADDRESS (Render):      https://______________.onrender.com
WEBSITE ADDRESS:              https://__________.web.app
```

---

## Part 0: Check your computer (10 minutes)

### Step 0.1: Open PowerShell in the project folder

1. Press the **Windows key**, type `PowerShell`, press **Enter**.
2. Copy-paste this and press **Enter**:

   ```powershell
   cd C:\abh_pers_od_tfr\google_ai_builder\Project_GCP_AI_Builder\policyc
   ```
3. ✅ The line starts with `PS C:\abh_pers_od_tfr\...\policyc>`

> Use this same window for the whole guide. If you close it, repeat Step 0.1.

### Step 0.2: Check the tools are installed

```powershell
git --version
node --version
npm --version
```

✅ Three version numbers appear. ❌ If one says "not recognized": install git from
<https://git-scm.com/download/win> (keep clicking Next) and/or Node "LTS" from <https://nodejs.org>,
then **close and reopen PowerShell** and redo Step 0.1.

### Step 0.3: Allow PowerShell to run helper scripts

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```
If it asks to confirm, type `Y` and press Enter.

### Step 0.4: Check the branch

```powershell
git branch --show-current
```
✅ You see `feature_updates_01`.

---

## Part 1: Get a Gemini API key for the live site (5 minutes)

Use a **new, separate key** for the live site, so your own testing cannot use up its daily allowance.

1. Open <https://aistudio.google.com/apikey> and sign in with Google.
2. Click **Create API key** → **Create API key in new project**.
3. ✅ A long text starting with `AIza...` appears. Click the **copy** icon and paste it in Notepad.

> 🔒 Treat it like a bank PIN. Never paste it into a chat, email, GitHub or screenshot.

---

## Part 2: Create the Firebase project (15 minutes)

### Step 2.1: Create the project

1. Open <https://console.firebase.google.com> and sign in with Google.
2. Click **Create a project**, name it `policyc`, click **Continue**.
3. If asked about **Google Analytics**: switch it **off**. Click **Create project**, wait, **Continue**.
4. Click the ⚙ gear → **Project settings** and find **Project ID** (like `policyc-a1b2c`). Write it in Notepad.
5. Your website address will be `https://<PROJECT ID>.web.app`. Write it in Notepad.

> 💰 The plan (bottom-left) must say **Spark**. Never click **Upgrade**.

### Step 2.2: Turn on "Sign in with Google"

1. Left menu → **Build** → **Authentication** → **Get started**.
2. **Sign-in method** tab → **Google** → switch **Enable** on.
3. **Public-facing name:** `PolicyC`. **Support email:** pick yours. Click **Save**.
4. ✅ "Google" shows **Enabled**.

### Step 2.3: Register the website and copy its settings

1. ⚙ gear → **Project settings** → scroll to **Your apps** → click the **`</>`** (Web) icon.
2. **App nickname:** `policyc-web`. Leave "Firebase Hosting" **unticked**. Click **Register app**.
3. Copy these values (the text inside the quotes) into Notepad:
   `apiKey`, `authDomain`, `messagingSenderId`, `appId`.
4. Click **Continue to console**.

(These Firebase values are **not secret**; they are made to be public in a website.)

### Step 2.4: Switch on Hosting

Left menu → **Build** → **Hosting** → **Get started** → click **Next / Next / Continue to the console**
(ignore the commands shown). ✅ You see a Hosting page with a domain like `policyc-a1b2c.web.app`.

---

## Part 3: Put the code on GitHub (15 minutes)

Render reads your code from GitHub, so it must live there. It must be in **your own** GitHub account.

### Step 3.1: Make a GitHub account (skip if you have one)

Go to <https://github.com/signup>. Write your username in Notepad.

### Step 3.2: Create an empty repository

1. Open <https://github.com/new>.
2. **Repository name:** `policyc`. Choose **Public** (the hackathon needs it public anyway).
3. **Do not** tick "Add a README", ".gitignore" or "license" (leave everything empty).
4. Click **Create repository**.
5. ✅ A page with a web address like `https://github.com/YOURNAME/policyc` appears. Write it in Notepad.

### Step 3.3: Save a snapshot of all the work (commit)

In PowerShell (project folder):

```powershell
git add -A
git status --short | Measure-Object | Select-Object -ExpandProperty Count
```
✅ A number appears (the files being saved; about 190 to 200).

Before continuing, check that no secret file is included:

```powershell
git status --short | Select-String -Pattern "\.env$|\.env\.|\.pem|\.key"
```
✅ Nothing is printed, or only lines mentioning `.env.example`. ❌ If you see `backend/.env`, stop:
that file holds your key. Run `git rm --cached backend/.env` and repeat.

Now save:

```powershell
git commit -m "PolicyC: workspace, engine checks, demo seed, Render deploy"
```
✅ It prints a summary like `NNN files changed`.

### Step 3.4: Upload to GitHub (push)

Replace `YOURNAME` with your GitHub username:

```powershell
git remote add deploy https://github.com/YOURNAME/policyc.git
git push deploy feature_updates_01:main
```

A browser window or login box appears: sign in to GitHub and click **Authorize**.
✅ The terminal ends with something like `feature_updates_01 -> main`.

Open your repository page and refresh. ✅ You see the folders `backend`, `frontend`, `deploy`, `docs`
and the files `Dockerfile`, `render.yaml`.

> If `remote add` says "remote deploy already exists", run `git remote set-url deploy https://github.com/YOURNAME/policyc.git` and push again.

---

## Part 4: Create the engine on Render (25 minutes, mostly waiting)

### Step 4.1: Connect Render to GitHub

1. Open <https://dashboard.render.com> (you are already signed in).
2. Click **New +** (top right) → **Web Service**.
3. Choose **Build and deploy from a Git repository** → **Next**.
4. Click **Connect GitHub** (or **Configure account**), sign in, and allow access.
   Choose **Only select repositories** → pick `policyc` → **Install**.
5. ✅ Your `policyc` repository appears in the list. Click **Connect** next to it.

### Step 4.2: Fill in the settings (one page, go slowly)

| Field | What to type or pick |
|---|---|
| **Name** | `policyc-api` |
| **Region** | `Singapore (Southeast Asia)` |
| **Branch** | `main` |
| **Root Directory** | leave empty |
| **Runtime / Language** | **Docker** (Render usually detects it; if you must choose, pick Docker) |
| **Dockerfile Path** | leave the default `./Dockerfile` |
| **Instance Type** | **Free** ($0 / month, 512 MB) |

Scroll down: click **Advanced** (if collapsed) and set **Health Check Path** to `/api/health`.

### Step 4.3: Add the settings (environment variables)

Still on that page, find **Environment Variables** → **Add Environment Variable**. Add these four
(name on the left, value on the right):

| Name | Value |
|---|---|
| `PC_GEMINI_API_KEY` | your Gemini key from Part 1 |
| `PC_FIREBASE_PROJECT_ID` | your Firebase **Project ID** |
| `PC_CORS_ORIGINS` | `https://PROJECTID.web.app,https://PROJECTID.firebaseapp.com` (replace both `PROJECTID`; no spaces) |
| `PC_GEMINI_BACKEND` | `developer` |

> ⚠️ Typos here are the #1 cause of problems. Zoom in and compare every character.

### Step 4.4: Create it

1. Make sure the price on the page says **$0** / **Free**. If it asks for a card, stop (see Part 9).
2. Click **Create Web Service** (or **Deploy**).
3. ✅ A log page opens. Wait for the build: first **Building** (5 to 10 minutes), then **Deploying**,
   then a green **Live** badge at the top.
4. At the top of the page you will see your engine's address, like `https://policyc-api.onrender.com`
   (Render sometimes adds letters, such as `policyc-api-x1y2`). **Copy exactly what you see** into Notepad.

### Step 4.5: Test the engine

Open this in your browser (use your **ENGINE ADDRESS**):

```
https://policyc-api.onrender.com/api/health
```
✅ You should see exactly: `{"status":"ok"}`

(The very first time it can take a minute to answer. That is the free "wake up".)

Then open the same address ending in `/api/samples`.
✅ You see a long list mentioning `expense`, `loto`, `account` and `"precomputed":true`.

---

## Part 5: Tell the website where the engine is (10 minutes)

### Step 5.1: Create the website settings file

```powershell
Copy-Item frontend\.env.example frontend\.env.production
notepad frontend\.env.production
```

Replace the contents with this, using **your** values. Keep the names on the left exactly. **No spaces
around `=`, no quotes, no `/` at the end.**

```
VITE_API_BASE=https://policyc-api.onrender.com
VITE_FIREBASE_API_KEY=AIza...your apiKey...
VITE_FIREBASE_AUTH_DOMAIN=YOURPROJECTID.firebaseapp.com
VITE_FIREBASE_PROJECT_ID=YOURPROJECTID
VITE_FIREBASE_APP_ID=1:123456789:web:abcdef...
VITE_FIREBASE_MESSAGING_SENDER_ID=123456789
```
**Ctrl+S**, close Notepad.

### Step 5.2: Allow the website to talk to the engine

1. Run `notepad firebase.json`.
2. Press **Ctrl+F** and search `YOUR-SERVICE.onrender.com` (exactly one match).
3. Replace it with your engine address **without** `https://`, for example `policyc-api.onrender.com`.
4. **Ctrl+S**, close.

### Step 5.3: Tell Firebase which project to use

```powershell
Copy-Item .firebaserc.example .firebaserc
notepad .firebaserc
```
Replace `YOUR-FIREBASE-PROJECT-ID` with your Project ID (keep the quotes). Save, close.

---

## Part 6: Put the website on Firebase (15 minutes)

### Step 6.1: Install the Firebase tool (one time)

```powershell
npm install -g firebase-tools
firebase --version
```
✅ A version number appears. ❌ If "running scripts is disabled": redo Step 0.3 and reopen PowerShell.

### Step 6.2: Log in

```powershell
firebase login
```
A browser tab opens: choose the **same Google account** as Part 2 and click **Allow**.
✅ `Success! Logged in as ...`

### Step 6.3: Build the website

```powershell
cd frontend
npm ci
npm run build
cd ..
```
✅ Near the end: `built in ...s` with no red errors (a yellow "chunks larger than 500 kB" is fine).

### Step 6.4: Publish it

```powershell
firebase deploy --only hosting
```
✅ `Deploy complete!` and `Hosting URL: https://YOURPROJECTID.web.app`. Open it.
✅ You see the PolicyC home page: "Software gets compiled and tested before it ships."

---

## Part 7: Test it like a real visitor (10 minutes)

Use an **Incognito / Private window**. Free engines sleep, so the first click may take a minute.

| # | Do this | ✅ You should see |
|---|---|---|
| 1 | Open your **WEBSITE ADDRESS** | Home page, possibly a sign-in screen |
| 2 | Click **Explore the demo as guest** (if shown) | Home page with sample cards |
| 3 | Click **Try it** on **Employee Expense Reimbursement** | A workspace with a score ring and a list of problems |
| 4 | Click **Decision does not cover all cases** | A clause highlights on the left and a flowchart box pulses |
| 5 | Sign in with Google | A Google popup, then your name/picture at top right |
| 6 | Click **Explain & fix** on that problem | An explanation with a before/after wording |
| 7 | Click **Accept**, then **Apply & recompile** | A progress bar, then "1 fixed · 0 new · 10 remaining" |

Bonus test (live compile): on the home page, upload a small `.txt` file that has numbered clauses
(for example `backend/seed/samples/leave/sop.md` from this folder). It compiles in about a minute.

---

## Part 8: Before you submit

### Step 8.1: Keep the engine awake for the judges (free, 5 minutes, optional but wise)

Free engines sleep after 15 minutes. A free "uptime monitor" visits it every 5 minutes so it never sleeps.

1. Open <https://uptimerobot.com> → **Register for FREE** (no card).
2. Click **+ New monitor** → type **HTTP(s)**.
3. **Friendly name:** `policyc`. **URL:** `https://policyc-api.onrender.com/api/health` (your engine address).
4. **Monitoring interval:** 5 minutes. Click **Create monitor**.
5. ✅ The monitor turns green ("Up").

(Render gives 750 free hours a month, which is enough to run one service all month.)

### Step 8.2: Ask the organisers (important, 5 minutes)

The rules say the project must be "deployed on Google Cloud via Cloud Run or Firebase". Your website
is on Firebase, but the engine is on Render (to keep it free). Whether that is accepted is **not
confirmed**. Send this (email, WhatsApp group, or the support link on the Hack2skill page) and keep the reply:

> Hello, we are Team [name], registered for the Google Cloud AI Builder Cup 2026 (JAPAC). Our frontend
> is deployed on Firebase Hosting and uses Firebase Authentication and the Gemini API. Because we have
> no billing account, our backend runs on Render's free tier, not Cloud Run. Does this split deployment
> meet the "deployed on Google Cloud via Cloud Run or Firebase" requirement? If not, what is the
> minimum we need to change? Thank you.

### Step 8.3: Things to hand in

* Website address: `https://YOURPROJECTID.web.app`
* GitHub repository link (it is already public)
* Video and deck: see `docs/SUBMISSION_CHECKLIST.md` and `docs/DEMO_SCRIPT.md`

---

## Part 9: When something goes wrong

After changing a **Render setting**, it redeploys by itself (a few minutes). After changing a **website
file**, repeat Steps 6.3 and 6.4. After changing **code**, repeat Steps 3.3 and 3.4 (Render rebuilds by itself).

| What you see | Probable cause | Fix |
|---|---|---|
| Render asks for a **credit card** at some step | You picked a paid instance type | Choose **Free**. If there is no free option, stop and ask for help |
| Render build fails with `no such file ... requirements-lite.txt` | The file did not reach GitHub | Run `git add -A`, `git commit -m "add file"`, `git push deploy feature_updates_01:main`. Check the file is visible on GitHub under `backend/` |
| Render says **Out of memory** / the service restarts | Too much at once | Open Render → your service → **Logs**. This should not happen in lightweight mode; send the last 30 lines for help |
| Render says **Deploy failed** / **Exited with status 1** | A setting is missing or misspelt | Check Step 4.3 spelling; open **Logs** and look at the last red lines |
| `/api/health` loads forever | The free engine is waking up | Wait up to 90 seconds and refresh |
| Browser shows a red error "blocked by CORS policy" (press F12 → Console) | `PC_CORS_ORIGINS` is wrong | Render → service → **Environment** → fix `PC_CORS_ORIGINS` so it contains `https://YOURPROJECTID.web.app` exactly (no spaces, no `/` at the end) → **Save** |
| Website loads but sample cards are empty, or "Failed to fetch" | Engine asleep or `VITE_API_BASE` wrong | Open the engine's `/api/health`; if OK, recheck `frontend\.env.production` (Step 5.1), then repeat Steps 6.3 and 6.4 |
| Popup says `auth/unauthorized-domain` | Firebase does not know your website | Firebase console → Authentication → Settings → **Authorized domains** → **Add domain** → `YOURPROJECTID.web.app` |
| Sign-in popup does nothing | Popups blocked | Click the 🚫 icon in the address bar → Always allow popups for this site |
| "Sign in required" when pressing a button | You are a guest | Sign in with Google first |
| Upload says "no PDF/Word/HTML reader (lightweight mode)" | Expected on the free engine | Upload a `.txt` or `.md`, or use the sample procedures |
| "Extraction failed ... daily quota exhausted" | Gemini's free daily allowance is used up | Wait until tomorrow, or make another key (Part 1) and replace `PC_GEMINI_API_KEY` in Render → Environment. Sample fixes still work from saved results |
| `/api/samples` is empty | Demo data not loaded | Render → service → **Manual Deploy** → **Clear build cache & deploy**; check Logs for `seed: loaded 9 demo project(s)` |
| `git push` says "Authentication failed" / "Repository not found" | Wrong login or wrong address | Check the repository address; run `git remote -v`; sign in to GitHub in the popup with the account that owns the repo |
| `firebase deploy` says "not logged in" | Login expired | Run `firebase login` again |
| `firebase deploy` says "Hosting site not found" | Hosting not started | Redo Step 2.4 |
| `npm ci` shows red `ERR!` | Wrong folder or no internet | The prompt must end with `...\policyc\frontend>`; check internet; retry |
| Website looks old after a deploy | Browser remembered the old page | Press **Ctrl+F5** or use Incognito |

---

## Part 10: Updating later

* **Engine or code changed:** `git add -A`, `git commit -m "update"`, `git push deploy feature_updates_01:main`. Render rebuilds by itself.
* **Website changed:** repeat **Steps 6.3 and 6.4**.
* **Settings changed on Render:** edit them under **Environment**; it redeploys by itself.

## Safety rules (please read)

1. Never share the **Gemini key** (chat, email, GitHub, screenshots). The repository must never contain `backend/.env`.
2. Do not upload confidential company documents. The free Gemini tier may use inputs to improve Google's products.
3. If a key leaks: <https://aistudio.google.com/apikey> → delete it, create a new one, update it in Render → Environment.

---

*Technical notes for developers: [DEPLOY_REFERENCE.md](DEPLOY_REFERENCE.md). The full-size image
(`Dockerfile.full`, with PDF/DOCX parsing) is for self-hosting on a machine with 4 GB or more of memory.*
