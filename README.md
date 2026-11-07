# Copart & IAAI Dodge Challenger AI Vision Scraper

An automated web scraper and AI vision inspector for **Copart** and **IAAI** salvage auctions built with **Playwright** (with anti-bot stealth measures) and the **Google GenAI SDK (`google-genai`)** using **`gemini-2.5-flash`**.

## Project Structure

```text
copart-ai-scraper/
├── main.py             # CLI entrypoint & pipeline orchestrator
├── config.py           # Target Copart/IAAI URLs, environment settings, and browser headers
├── scraper.py          # Playwright stealth scraper for Copart & IAAI search + detail pages
├── analyzer.py         # Gemini 2.5 Flash Vision evaluation with strict Pydantic schema
├── notifier.py         # Terminal summary & Telegram Bot alert dispatcher
├── requirements.txt    # Python package dependencies
├── .env.example        # Environment variables template
└── README.md           # Step-by-step local setup and usage guide
```

---

## Evaluation Rules Enforced by Gemini (`gemini-2.5-flash`)

1. **PASS COLOR**:
   - **Pitch Black** (Black)
   - **Granite / Granite Crystal** (Dark/Metallic Gray)
   - **Plum Crazy / Hellraisin** (Purple)
   - *All other colors (White, Red, Blue, Green, Yellow, Orange, etc.) are automatically rejected.*
2. **PASS DAMAGE**:
   - Strictly superficial or bolt-on front or rear damage (bumper cover, grille, hood, fenders, headlights, taillights, trunk lid).
3. **REJECT DAMAGE**:
   - Immediately rejected if Gemini detects **deployed airbags**, **bent roof**, **damaged A/B/C pillars**, **ripped/collapsed suspension**, or **heavy structural crush**.

---

## Step-by-Step Local Setup Instructions

### 1. Create and Activate a Virtual Environment

**Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 3. Install Playwright Chromium Browser

```bash
playwright install chromium
```

### 4. Configure Environment Variables (`.env`)

Copy `.env.example` to `.env`:

**Windows (PowerShell):**
```powershell
Copy-Item .env.example .env
```

**macOS / Linux:**
```bash
cp .env.example .env
```

Open `.env` and fill in your credentials:
```ini
GEMINI_API_KEY=your_actual_gemini_api_key
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_optional
TELEGRAM_CHAT_ID=your_telegram_chat_id_optional
HEADLESS=false
MAX_LISTINGS_PER_SOURCE=10
MAX_IMAGES_PER_LISTING=6
```
- **`GEMINI_API_KEY`** *(Required)*: Create an API key in [Google AI Studio](https://aistudio.google.com/apikey).
- **`TELEGRAM_BOT_TOKEN` & `TELEGRAM_CHAT_ID`** *(Optional)*: If provided, every `PASS` vehicle triggers an instant Telegram notification with the listing link, identified color, and damage summary. Even without Telegram configured, all `PASS` and `REJECT` evaluations are printed clearly in your terminal.

---

## Running the Scraper Locally

### Standard Run (Scrapes both Copart and IAAI in visible browser mode)
Running in headful mode (`HEADLESS=false` or `--headful`) is recommended because Copart and IAAI use Cloudflare/Imperva WAF protection:

```bash
python main.py --headful
```

### Common CLI Options

- **Check only the newest listings from today (last 24h):**
  ```bash
  python main.py --headful --only-today --limit 10
  ```
- **Baseline Snapshot (Mark all currently listed cars as "already seen" without calling Gemini API):**
  Run this once so `seen_lots.json` stores all older listings currently on Copart & IAAI. Every subsequent run of `python main.py --headful` will then check **only brand-new cars added after that moment**:
  ```bash
  python main.py --headful --mark-existing-seen
  ```
- **Scrape only Copart or only IAAI:**
  ```bash
  python main.py --source copart --limit 5
  python main.py --source iaai --limit 5
  ```
- **Adjust the number of listings or images analyzed per vehicle:**
  ```bash
  python main.py --limit 15 --max-images 10
  ```
- **Re-analyze listings that were already checked in previous runs (`seen_lots.json`):**
  ```bash
  python main.py --ignore-seen
  ```
- **Run in headless mode:**
  ```bash
  python main.py --headless
  ```

---

## Automatyzacja przez GitHub Actions (Codzienne Uruchamianie)

W repozytorium znajduje się gotowy plik workflow: `.github/workflows/daily_scraper.yml`.

### 1. Dodaj Sekrety (API Keys) na GitHubie
Wejdź w swoje repozytorium na GitHubie:
**Settings** → **Secrets and variables** → **Actions** → **New repository secret** i dodaj:
- `GEMINI_API_KEY` *(Wymagany)* — Twój darmowy klucz z Google AI Studio
- `TELEGRAM_BOT_TOKEN` *(Opcjonalny, ale zalecany)* — token bota z `@BotFather`
- `TELEGRAM_CHAT_ID` *(Opcjonalny, ale zalecany)* — Twoje ID czatu na Telegramie

### 2. Jak działa Workflow:
- **Codzienny harmonogram (`cron: "0 8 * * *"`)**: Uruchamia się automatycznie codziennie rano (08:00 UTC = 09:00 czasu zimowego / 10:00 letniego w Polsce).
- **Wirtualny ekran `xvfb-run`**: Uruchamia przeglądarkę Chromium w trybie `--headful` na wirtualnym ekranie serwera Ubuntu, dzięki czemu trudniej wykryć bota przez Cloudflare niż w zwykłym trybie headless.
- **Pamięć sprawdzonych aut (`seen_lots.json`)**: Po każdym przebiegu GitHub Actions automatycznie dopisuje nowe sprawdzone numery Lot do pliku `seen_lots.json` i robi commit do repozytorium, dzięki czemu kolejnego dnia sprawdzane są **tylko nowe ogłoszenia**.
- **Ręczne uruchomienie (`Run workflow`)**: W zakładce **Actions** możesz w każdej chwili kliknąć **Run workflow** i wybrać:
  - `mark_existing_seen` — jednorazowe zapisanie wszystkich obecnych aut do `seen_lots.json` bez wywoływania Gemini,
  - `analyze` — normalne sprawdzenie najnowszych ogłoszeń przez Gemini AI.

---

## 📱 Aplikacja PWA "Salvage Swipe" (React + Darmowy Firebase)

W folderze `web/` znajduje się aplikacja **PWA (Progressive Web App)** w stylu Tindera dla aut, które przeszły selekcję AI (`PASS`):
- **Swipe (Tinder dla aut)**:
  - **W prawo (`❤️ ULUBIONE` lub strzałka `→`)** — zapisuje auto w zakładce **Ulubione**.
  - **W lewo (`📁 SCHOWEK` lub strzałka `←`)** — odkłada auto do zakładki **Schowek** (nic nie ginie, w każdej chwili możesz przenieść auto ze Schowka do Ulubionych).
- **Kopiowanie VIN + 1-klik do Bid.Cars**: Każda karta posiada przycisk kopiowania numeru VIN oraz bezpośredni link **Sprawdź cenę na Bid.Cars**, aby jednym kliknięciem sprawdzić archiwum aukcji i cenę sprzedaży.
- **Konfigurator Filtrów i URL (`Filtry`)**:
  - **Kreator filtrów** (Marka, Model, Rocznik od-do, Maks. przebieg, Cylindry, Status Run & Drive, Uszkodzenia, Dozwolone kolory AI, Wyjątek dla aut po tuningu) — automatycznie generuje URL do Copart oraz IAAI.
  - **Tryb własnych linków URL** — możesz też wkleić bezpośrednio swój link z filtrami z Copart i IAAI.
- **Powiadomienia o nowych autach**: Aplikacja wysyła powiadomienia przeglądarkowe/PWA oraz baner w czasie rzeczywistym, gdy GitHub Actions doda nowe auto (`PASS`).

### 1. Uruchomienie aplikacji lokalnie
```bash
cd web
npm install
npm run dev
```
*(Podczas pracy lokalnej lub przed podpięciem Firebase aplikacja automatycznie wczytuje auta z pliku `/passed_cars.json` i zapisuje Twoje wybory w pamięci przeglądarki `localStorage`).*

### 2. Darmowy Hosting i Baza Danych na Firebase (100% Plan Spark = 0 zł, bez karty!)
Całość została zaprojektowana tak, aby korzystać **wyłącznie z bezpłatnego planu Firebase Spark (0 zł)**:
- **Brak płatnych Cloud Functions i brak płatnego Storage** (zdjęcia ładowane są bezpośrednio z serwerów Copart/IAAI, a scraper działa za darmo na GitHub Actions).
- **Cloud Firestore (Darmowy limit: 50 000 odczytów / 20 000 zapisów dziennie)** trzyma listę znalezionych aut, statusy (`Ulubione` / `Schowek`) oraz Twoje ustawienia filtrów.

#### Krok po kroku — wdrożenie na Firebase:
1. Wejdź na [Firebase Console](https://console.firebase.google.com/) i utwórz darmowy projekt (plan **Spark – Free**).
2. W menu po lewej kliknij **Build → Firestore Database → Create database** i wybierz start w trybie produkcyjnym lub testowym (reguły są w pliku `firestore.rules`).
3. W **Project Settings (koło zębate) → General → Your apps** kliknij ikonę Web (`</>`) i skopiuj parametry konfiguracji Firebase.
4. Utwórz plik `web/.env` (na wzór `web/.env.example`) i wklej swoje dane projektu Firebase (`VITE_FIREBASE_PROJECT_ID`, `VITE_FIREBASE_API_KEY`, itd.).
5. W repozytorium na GitHubie (**Settings → Secrets and variables → Actions**) dodaj sekret:
   - `FIREBASE_PROJECT_ID` — ID Twojego projektu Firebase (dzięki temu GitHub Actions po każdym uruchomieniu automatycznie wyśle nowe auta `PASS` do Twojej bazy Firestore i pobierze z niej ustawione przez Ciebie filtry!).
6. Zbuduj i wrzuć aplikację na darmowy **Firebase Hosting**:
   ```bash
   cd web
   npm run build
   cd ..
   npx firebase-tools login
   npx firebase-tools use TWOJE_FIREBASE_PROJECT_ID
   npx firebase-tools deploy --only hosting,firestore:rules
   ```
Po wdrożeniu otrzymasz link `https://twoj-projekt.web.app`, który możesz otworzyć na telefonie i kliknąć **"Dodaj do ekranu głównego" (Zainstaluj aplikację PWA)**.
