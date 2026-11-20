# TidyInvoice — E-Invoice Organization and Reimbursement Preparation

<div align="center">

**English** | [中文](README.md)

</div>




<div align="center">

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-Apache--2.0-blue)
![Recognition](https://img.shields.io/badge/Recognition-Local%20Parse%20%2B%20OCR-purple)
![Platform](https://img.shields.io/badge/Platform-Windows%2011%20%7C%20macOS-lightblue)
![Status](https://img.shields.io/badge/Status-Stable-brightgreen)

**Turn PDF, OFD, and XML e-invoices from your mailbox, plus supported invoice download links, into organized files and an Excel reimbursement summary.**

Designed for individuals, freelancers, and small teams that manually collect multiple e-invoices each month. Connect your own QQ Mail, 163 Mail, or 88 Mail account to collect invoices in batches, parse and OCR them locally, archive them by category, and create a summary while retaining unclear results for human review.

Download: [latest Windows installer / portable package and macOS (Apple Silicon) installer](https://github.com/woniu-zk/tidyinvoice/releases/latest)

*Email and invoice files are processed locally from start to finish: e-invoices are parsed directly, while scans and images go through the bundled local OCR. Recognition needs no network and no API key, and invoice content is never uploaded.*

</div>

<p align="center">
  <img src="./docs/images/tidyinvoice-logo.png" alt="TidyInvoice app icon" width="132" />
</p>

## DeepSeek Harness Plugin

`@woniu-zk/dsh-invoice-downloader` brings local IMAP invoice download, local parsing and OCR, archiving, and Excel summaries to a right-side DeepSeek Harness panel. It is intended for reimbursement workflows that automate repetitive organizing while keeping a human review step.

```sh
dsh plugin --profile web add @woniu-zk/dsh-invoice-downloader
dsh web --profile web
```

Open **Invoice Downloader** from the right-side entry, choose an output directory, install the local engine once, and enter a QQ Mail, 163 Mail, or 88 Mail IMAP authorization code. First-time setup needs network access to download Python dependencies and Chromium; the `rapidocr-onnxruntime` pip wheel includes the default PP-OCRv3 models, so no separate manual model download is required. Invoice files and recognized text are processed entirely on this machine; the plugin needs no model or API key. The plugin supports Windows x64 and macOS Apple Silicon. The DSH credential service stores authorization codes, never plugin settings or scan logs.

---

## ✨ Key Highlights

| &nbsp; | Feature | Description |
|--------|---------|-------------|
| 🔒 | **One-click launch, ready to use** | Extract and run — no need to install Python or any dependencies |
| 🔎 | **Local recognition engine** | PDF text layers, OFD, and digital-invoice XML are parsed directly; scans and images go through bundled local OCR — no network or API key needed |
| 🔍 | **Four-layer smart funnel** | Whitelist domains → Subject keywords → Body detection → QR code scanning, precisely filtering non-invoice emails |
| 📄 | **Link-based invoice auto-recovery** | Playwright automatically opens Baiwang Cloud and tax platform links, downloading official PDF archives |
| 🧾 | **Automatic invoice/document pairing** | Hotel invoice/folio and ride invoice/itinerary pairs are archived with adjacent names |
| 🪟 | **Quiet background processing** | URL workers, Node, and Chromium run without repeatedly opening console windows |
| 🗂️ | **Open expense classification rules** | Built-in defaults + user rules + global custom invoice types + seller dictionary + rule packs; target type and amount range generate archive folders automatically; unmatched invoices go to review |
| 📂 | **Local folder organizing** | Works without any mailbox: one-click offline organizing of phone exports, WeChat/Alipay download folders, and photographed receipts; archives in place and keeps originals verbatim under `整理前发票/` |
| 📥 | **Fetch to inbox only** | Saves attachments plus a source manifest into `inbox/` without parsing or renaming, ready for your own tools or a later organizing step |
| 📊 | **One-click Excel report** | Automatically generates `invoice-summary_<timestamp>.xlsx`, covering invoice lists and amount summaries |

---

## 🏗️ Overall Workflow

```mermaid
flowchart LR
    A["📧 QQ / 163 / 88\nMailbox IMAP"] --> B["📥 Email Fetching\nEmailFetcher"]
    B --> C{"🔍 Four-layer\nSmart Funnel"}
    C -->|"Pass"| D["📎 Attachment Extraction\nZIP Recursive Unpack"]
    C -->|"Discard"| X["🗑️ Non-invoice Emails"]
    D --> E{"Attachment Type?"}
    E -->|"PDF/OFD/XML"| F["🔎 Local Recognition\nPDF text / OFD / Invoice XML\nLocal OCR → Rule Extraction"]
    E -->|"URL Link"| G["🌐 PDF Recovery\nPlaywright"]
    G --> F
    F --> H{"Recognition\nSuccessful?"}
    H -->|"✅"| I["📂 Smart Classification\nRule-based Renaming"]
    H -->|"❌"| J["📁 Manual Review"]
    I --> K["🗂️ Local Archiving"]
    K --> L["📊 Excel Report"]
```

---

## 🔎 Local Recognition Chain

Recognition runs entirely on this machine in the order "deterministic parsing first → local OCR fallback → rule extraction and checks". No network access, API key, or model service is involved.

> **Processing order**
> - **Text-layer PDF**: layout text is read directly with PyMuPDF, without OCR
> - **OFD / digital-invoice / VAT XML**: parsed directly by container structure and field aliases
> - **Scans and images**: handled by the bundled local OCR (RapidOCR + ONNX Runtime; models ship with the dependency)
> - **Rule extraction**: fields are mapped by anchor and regex rules, for example amounts are located via the "tax-inclusive total (in words) / (in figures)" anchors
>
> **Offline consistency checks**: verify that the amount plus tax reconciles with the tax-inclusive total, that dates are parseable, and that invoice numbers are valid digit strings; anything that cannot be confirmed is not guessed but routed to Manual Review for the user to check.

---

## 🧩 Expense Classification Rules

Expense categories are no longer hard-coded. Built-in rules provide factory defaults only; users can add rules, choose or create a target invoice type, enter a keyword and optional amount range, and maintain the same rules through the UI, a text editor, or the CLI.

- **Rule locations**
  - Global: `%APPDATA%\TidyInvoice\rules\` (macOS: `~/Library/Application Support/TidyInvoice/rules/`)
  - Current invoice library override: `<library>\rules\`
  - Files: `categories.yaml` (rules and keywords), `custom_types.yaml` (global custom invoice types), `user_terms.yaml` (seller → category), `rules.d/*.yaml` (optional rule packs)
- **Precedence**: current library rules → global rules → built-in defaults. Within one scope, rules match top-to-bottom and the first match wins; no priority is needed.
- **A rule only needs**: target invoice type, keyword, amount range (optional), enabled state. The archive folder is generated from "target type + amount range" — no manual folder entry.
- **Target invoice type**: choose a built-in type (taxi, hotel invoice, meal, etc.) or create a custom type in any scope. Custom types are stored globally in `custom_types.yaml`, are selectable by global and all library rules, and cannot be deleted while referenced by a rule.
- **Folder naming**: target type "酒店" with amount 100–200 produces `酒店-100-200/`; lower bound only produces `酒店-100以上/`; upper bound only produces `酒店-200以下/`; no amount range uses `酒店/`.
- **Matching order**: seller dictionary first, then user rules by keyword + amount in list order. The matched rule's target type decides the folder. Built-in defaults are the final fallback; if nothing matches, the invoice is marked unclassified and moved to Manual Review instead of being silently filed as "Other".
- **Types and recognition**: built-in types are recognized from the document; custom types are user-defined rule outputs and are not produced directly by recognition, but any keyword rule can target one.
- **Built-in defaults are editable too**: a built-in rule's target type, keywords, amount range, and enabled state can be changed; changes are saved as an override in the current scope. Single-rule and “restore all” actions require a second confirmation and let you choose “current scope only” or “global + current library”; the previous files are backed up first. Built-in rules keep their internal invoice-type fallback gate.
- **Why this category**: the rules page test panel and `rules test` / `rules explain` show the matched dictionary/rule, keyword, target type, archive folder, and source file line.
- **Backup and rollback**: every UI/CLI save copies the previous files to `rules/.backup/`; each scope can be reset to its defaults. Direct YAML edits take effect on the next organize run without a restart.

Example: create target type "酒店", then a rule with keyword "酒店住宿" and amount 100–200; it archives to `酒店-100-200/`. A 150-yuan hotel invoice goes there, while a 90-yuan one still goes to `住宿发票/` by its recognized type. The rule decides the folder; the file name still carries the document type.

UI entry: **Settings → Expense classification rules**. CLI:

```powershell
python organize_cli.py rules list
python organize_cli.py rules test --text "酒店住宿" --amount 150.00
python organize_cli.py rules types add 酒店
python organize_cli.py rules add-rule 酒店住宿 --type 酒店 --amount-min 100 --amount-max 200
python organize_cli.py rules validate
```

> Saving from the UI rewrites the current scope's rule file; edit the YAML directly if you want to preserve comments. Library rules match before global rules, and resetting a library falls back to global/built-in rules. Changing the target type, keyword, or amount range only affects future archives; existing files are not moved automatically.

---

## 🔍 Four-Layer Smart Filtering Funnel

The system does not run recognition on every email. Instead, it first passes through a four-layer funnel for precise filtering, reducing wasted recognition and false positives.

![Four-Layer Smart Filtering Funnel](docs/funnel.svg)

After passing the filter, attachments also go through a **three-tier decision process**:

| Tier | Trigger Condition | Handling |
|------|-------------------|----------|
| 🗑️ **Tier A** (Discard) | Tracking pixels, logos, decorative images (≤32px) | Skipped directly |
| 📦 **Tier B** (Hold) | Attachments >5MB, ZIP unpack failure | Retained but not processed |
| ✅ **Tier C** (Archive) | Normal PDF/OFD/XML | Enters local recognition pipeline |

---

## 🌐 Three-Tier PDF Recovery Strategy

Many invoice emails only contain "click to download" links. The system automatically identifies the platform and selects the optimal approach:

```mermaid
flowchart TD
    Link(["🔗 Invoice Links in Email"]) --> Detect{"Identify Link Platform"}
    Detect -->|"Baiwang Cloud"| BW["🏢 Playwright Automation\nLogin → Click Download → Capture File\nField Matching Verification"]
    Detect -->|"Tax Bureau · Nuonuo · Aisino"| DI["📥 Direct HTTP Download\nIdentify Invoice Family\nLocal Field Validation"]
    Detect -->|"Unknown Webpage"| Generic["🌐 Web to PDF\nDetect Login/Captcha\nA4 Format Rendering"]
    BW & DI & Generic --> Final(["📄 Local PDF"])
    Final --> Rec(["🔎 Local Recognition\nParsing / OCR / Rule Extraction"])
```

---

## 📂 Three Ways to Use It: Fetch and Organize Are Independent

| Mode | Best for | What it does |
|------|----------|--------------|
| **Fetch and organize** | Everyday use | Connects to the mailbox, extracts attachments, recognizes, classifies, renames, and archives them |
| **Fetch to inbox only** | You already have your own organizing tools | Saves attachments into `inbox/` and writes a `manifest.jsonl` source manifest; no parsing, renaming, or ledger |
| **Local folder organizing** | Invoices are already on this computer | Choose any folder (phone export, WeChat/Alipay downloads, photographed receipts); click "Start Organizing" to recognize, classify, rename, and archive in place, offline |

- Local folder organizing needs **no mailbox configuration and no network**; it is a one-click action with no preview step.
- Fetch-only and local organizing hand off through `inbox/` + `manifest.jsonl`; the organizer keeps the mail source information (mailbox, subject, sender, received time) in the archive record.
- Local folder organizing works in the **selected invoice folder itself** by default; the output folder defaults to the same path (and can still be changed):
  - classified copies go to category folders such as `打车/` and `住宿发票/`;
  - **originals are kept in `整理前发票/` exactly as they were**: same file name, same bytes, and the same sub-folder path — no renaming, no month sub-folders, never deleted;
  - duplicate files go to `duplicates/`;
  - the Excel report is written into the organizing folder, and unreadable files stay where they are.
- Re-running on the same folder is **idempotent**: already organized files are not archived or recognized again.

### Command line (optional)

A standalone CLI lives at the repository root for scripting and tool chaining:

```powershell
# Organize a local folder: preview by default, --apply performs the run
# (output defaults to the input folder, i.e. in-place organizing)
python organize_cli.py organize "D:\invoices\inbox"
python organize_cli.py organize "D:\invoices\inbox" --apply

# Or copy archived results into a separate library; originals stay in the input folder
python organize_cli.py organize "D:\invoices\inbox" --output "D:\invoice-library" --apply

# Fetch mailbox attachments into inbox only (no parsing; env:VAR reads the auth code)
python organize_cli.py fetch --email you@qq.com --auth-code env:QQ_AUTH_CODE --output "D:\invoice-library"
```

Each `manifest.jsonl` line records one attachment's source (`sha256`, relative path, mailbox, UID, subject, sender, received time, and so on). The format is public, hand-editable, and readable by other scripts.

---

## ⚙️ Configuration Guide

> Only needs to be configured once on first use (email address and authorization code); after that, just click run for each scan. The recognition engine is built in — no model or API key required.

### Step 1 · Enable 163 Mailbox IMAP

<details>
<summary>📖 Click to expand detailed steps for 163 mailbox</summary>

**Server Parameters**

| Parameter | Value |
|-----------|-------|
| IMAP Server | `imap.163.com` |
| Port | `993` (SSL/TLS) |

**Setup Steps**

1. Log in to [mail.163.com](https://mail.163.com), click **Settings** in the upper right corner
2. Select **POP3/SMTP/IMAP** from the dropdown menu
3. Find **IMAP/SMTP Service**, click the **Enable** button on the right
4. An "Account Security Verification" window will appear:
   - **QR Code Method** (Recommended): Scan the QR code with your phone to automatically send a verification SMS
   - **Manual Method**: Manually send an SMS to the designated number as prompted
5. After sending the SMS, click **I Have Sent It**
6. The system generates a **16-character authorization code** (letter combination, **only displayed once — copy and save it immediately**)

> ⚠️ The authorization code is not your mailbox login password. It is a separate password specifically for third-party clients, and it is case-sensitive.

📚 [163 Mailbox Official Help](https://help.mail.163.com/)

</details>

---

### Step 2 · Enable QQ Mailbox IMAP

<details>
<summary>📖 Click to expand detailed steps for QQ mailbox</summary>

**Server Parameters**

| Parameter | Value |
|-----------|-------|
| IMAP Server | `imap.qq.com` |
| Port | `993` (SSL/TLS) |

**Setup Steps**

1. Log in to [mail.qq.com](https://mail.qq.com), click the **Settings** icon in the upper right corner
2. Select the **Account** tab
3. Find **POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV Service**
4. Click **Manage Service** → **Enable Service**
5. Click **Generate Authorization Code** and complete identity verification:
   - **QR Code Method** (Recommended): Scan the QR code with your phone to automatically send a verification SMS
   - **Manual Method**: Send "Configure Email Client" to **1069070069** using your QQ-linked phone
6. Click **I Have Sent It** — the authorization code is generated instantly after verification (**save it immediately**)

> ⚠️ The authorization code automatically becomes invalid after changing your QQ password and must be regenerated.

📚 [QQ Mailbox Official Help](https://service.mail.qq.com/detail/0/339)

</details>

---

### Step 3 · Enable 88 Mailbox IMAP

<details>
<summary>📖 Click to expand detailed steps for 88 mailbox</summary>

**Server Parameters**

| Parameter | Value |
|-----------|-------|
| IMAP Server | `imap.88.com` |
| Port | `993` (SSL/TLS) |
| Username | Full email address |
| Password | Dedicated password generated in the mailbox settings |

**Steps**

1. Log in to [mail.88.com](https://mail.88.com) and open **Settings** → **POP Settings**
2. Confirm that **IMAP/SMTP service** is enabled
3. In the **Dedicated Password** section, click **Add Dedicated Password**
4. Enter a name (for example, `TidyInvoice`) and copy the generated random password immediately
5. In the app, enter the full email address and put the dedicated password in the authorization code field

> ⚠️ The dedicated password is not your mailbox login password. It is intended for third-party mail clients, so keep it separately.

</details>

---

## 🚀 Quick Start

### Windows (installer / portable)

1. Installer: run `TidyInvoice-*-windows-x64-setup.exe`. Portable: extract `TidyInvoice-*-windows-x64-portable.zip` to a regular folder (avoid cloud-sync directories) and keep `_internal` beside `TidyInvoice.exe`.
2. Double-click `TidyInvoice.exe`; the settings interface appears on first launch.
3. Enter your email address and authorization code (QQ, 163, or 88), then click "Start Scanning". Recognition runs offline on this machine — scans and images are handled by the bundled OCR, with no network or API key needed. Invoices are archived to the "Invoice Organizer" folder on your desktop.

### macOS (Apple Silicon)

1. Open `TidyInvoice-*-macos-arm64.dmg` and drag `TidyInvoice` to Applications.
2. The settings interface appears on first launch. This build is unsigned and not notarized; if macOS blocks it, confirm opening it in **System Settings → Privacy & Security**.
3. Enter your email address and authorization code (QQ, 163, or 88), then click "Start Scanning". Recognition runs offline on this machine — scans and images are handled by the bundled OCR, with no network or API key needed.

---

## 📁 Output Directory Structure

```
Invoice Organizer/
├── inbox/             ← Fetch-only handoff folder (contains manifest.jsonl)
├── Train Tickets/
│   └── 20260315-Beijing-Shanghai-Train-Ticket.pdf
├── Flight Tickets/
│   └── 20260301_Flight_1280.00_Air-China.pdf
├── Hotel Invoices/
│   ├── 20260310-Hotel-01-Invoice_888.00.pdf
│   └── 20260310-Hotel-01-Folio_888.00.pdf
├── Taxi/
│   ├── 0312-DiDi-01-Invoice_45.50.pdf
│   └── 0312-DiDi-01-Itinerary_45.50.pdf
├── Dining/
├── Manual Review/     ← Materials that cannot be confirmed reliably
├── Non-target Company Invoices/
└── invoice-summary_<timestamp>.xlsx
```

---

## ❓ FAQ

<details>
<summary>Q: White screen or no response after launching the software?</summary>

- Make sure the **entire archive is extracted**; the `_internal` folder must be in the same directory as `TidyInvoice.exe`
- Avoid placing the software in a directory containing **Chinese characters or spaces**

</details>

<details>
<summary>Q: Very few invoices found after scanning?</summary>

- In the software's time range settings, **adjust the start date to more than 180 days ago**
- Some mailboxes default to fetching only the last 30 days of emails — select "Fetch all emails" in the mailbox IMAP settings

</details>

<details>
<summary>Q: Authentication failure after entering the authorization code?</summary>

- **QQ Mailbox**: Must be obtained through "Manage Service → Generate Authorization Code" — it is **not your QQ password**
- **163 Mailbox**: Must be generated from the "Enable IMAP Service" popup — it is **not your mailbox login password**, and it is case-sensitive
- **88 Mailbox**: Use the dedicated password generated under "Settings → POP Settings → Add Dedicated Password" — it is **not your mailbox login password**
- The QQ authorization code must be regenerated after changing your QQ password

</details>

<details>
<summary>Q: Does recognition need network access or an API key?</summary>

No. E-invoices are parsed directly on this machine, and scans or images go through the bundled local OCR whose models ship with the software. Recognition never goes online, never calls a model service, and requires no API key.

</details>

<details>
<summary>Q: Some invoices end up in the Manual Review folder?</summary>

This is normal. When local parsing and rule checks cannot confirm a result reliably, the system places the invoice in the Manual Review folder for human confirmation. This is usually caused by blurry images, non-standard documents, or encrypted PDFs.

</details>

<details>
<summary>Q: Why does an invoice say "no classification rule matched"?</summary>

When no expense category rule matches, the invoice is marked unclassified and moved to Manual Review instead of being silently filed under "Other". Add a seller/item keyword, invoice type, or amount rule under **Settings → Expense classification rules**, save it, move the file back into the invoice folder, and organize again.

</details>

<details>
<summary>Q: What does the target invoice type in a rule do?</summary>

The target type is what the rule outputs when it matches, and it determines the archive folder and classification result. You can choose a built-in type (taxi, hotel invoice, meal, etc.) or create a custom type. Built-in types are recognized from the document; custom types are user-defined rule outputs, are available globally, and are not produced directly by recognition.

</details>

<details>
<summary>Q: How is the archive folder name generated?</summary>

You do not enter it manually. It is built from the target type and amount range: target type "酒店" with amount 100–200 produces `酒店-100-200/`; a lower bound only produces `酒店-100以上/`; an upper bound only produces `酒店-200以下/`; no amount range uses `酒店/`. Changing the target type, keyword, or range affects future archives only; existing files are not moved automatically.

</details>

<details>
<summary>Q: Can built-in rules be edited, and is restoring defaults safe?</summary>

Yes. A built-in rule's target type, keywords, amount range, and enabled state can be edited; saving creates an override in the current scope. Single-rule and “restore all” actions open a confirmation dialog first, where you choose “current scope only” or “global + current library”. Only after confirmation are the overrides removed and the built-in defaults restored; the previous rule files are backed up automatically.

</details>

<details>
<summary>Q: Where are the classification rule files, and can I edit them?</summary>

Yes. Global rules live in `%APPDATA%\TidyInvoice\rules\` (macOS: `~/Library/Application Support/TidyInvoice/rules/`); library overrides live in `<library>\rules\`. The files are open YAML: `categories.yaml`, global custom types `custom_types.yaml`, `user_terms.yaml`, and optional `rules.d/*.yaml`. Every save is backed up under `.backup/`, and both the UI and CLI can reset a scope to its defaults.

</details>

---

## 🛡️ Privacy & Security

- All emails and invoice files are processed **locally** and are never uploaded to any server
- Mailbox credentials are encrypted with **DPAPI** on Windows and stored in **Keychain** on macOS
- Recognition runs entirely on this machine: e-invoices are parsed directly, scans and images go through the bundled OCR; no model service is called and no invoice content is sent

---

## ⚠️ Disclaimer

By using this software, you acknowledge and accept the following terms.

**Compliant Use** · This software accesses mailboxes through IMAP in **read-only** mode. It does not send, delete, or modify any emails. Users must ensure they have legitimate authorization for the mailboxes being processed.

**Purpose** · This software is intended only as an automation assistant for downloading, recognizing, classifying, and archiving invoice-related emails and files.

**Accuracy & Compliance** · The author does not warrant the accuracy, completeness, legality, tax compliance, financial compliance, or accounting compliance of any invoice data or generated results. Users must independently verify all invoices, reimbursements, tax filings, accounting records, and compliance outcomes before relying on them.

**Data** · Recognition and archiving happen on this machine. No external model service is called, and invoice files or recognized text are never uploaded to a third party; original email content is never sent either.

**Liability** · The author is not liable for any losses, omissions, errors, failed reimbursements, tax risks, compliance issues, or data loss arising from use of this software.

**Third-Party Services**

| Service | Purpose | Provider |
|---------|---------|----------|
| QQ Mailbox IMAP | Email reading | Tencent Technology (Shenzhen) Co., Ltd. |
| 163 Mailbox IMAP | Email reading | NetEase (Hangzhou) Network Co., Ltd. |
| 88 Mailbox IMAP | Email reading | Perfect World |

---

## 🌱 Origin and Credits

This project is a derivative of [Invoice Downloader](https://github.com/EthanYoQ/Invoice-Downloader) by EthanYoQ / Yong Qi (Apache License 2.0), and continues development on top of it. The upstream copyright, license, and [NOTICE](NOTICE) attribution are retained under the same license.

The project is maintained independently by the community. It is not affiliated with, endorsed by, or certified by the upstream author; the product name, icon, release assets, and npm package do not represent the upstream project. Report upstream issues in the upstream repository and issues introduced here in [this repository](https://github.com/woniu-zk/tidyinvoice/issues).

Generally useful fixes are prepared as patches that can be sent upstream; see [docs/UPSTREAM.md](docs/UPSTREAM.md).

---

## 📜 License

The project's **own source code** is licensed under the [Apache License 2.0](LICENSE): commercial use, modification, distribution, and closed-source integration are permitted; redistributions must retain the copyright notice, the license text, the [NOTICE](NOTICE) attribution, and the third-party notices.

Published installers bundle the **AGPL-3.0 component PyMuPDF**, so a distributed build must provide the corresponding source to its recipients under AGPL-3.0; each package ships `LICENSE`, `NOTICE`, `THIRD_PARTY_NOTICES.md`, and `licenses/`. See [docs/LICENSING.md](docs/LICENSING.md) for the license structure, what you may and may not do, and commercial licensing options; the component inventory is in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

---

<div align="center">

Made with ❤️ by **Woniu (蜗牛)**

[Report Issues](https://github.com/woniu-zk/tidyinvoice/issues) · [163 Mailbox Help](https://help.mail.163.com/) · [QQ Mailbox Help](https://service.mail.qq.com/detail/0/339)

</div>
