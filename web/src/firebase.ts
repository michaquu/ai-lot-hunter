import { initializeApp, getApps } from "firebase/app";
import {
  getFirestore,
  collection,
  doc,
  setDoc,
  getDoc,
  getDocs,
  onSnapshot,
  Firestore,
} from "firebase/firestore";
import { CarListing, SearchFilterConfig, SwipeRecord } from "./types";

const GITHUB_PASSED_CARS_URL =
  "https://raw.githubusercontent.com/michaquu/ai-lot-hunter/main/passed_cars.json";
const GITHUB_SEARCH_CONFIG_URL =
  "https://raw.githubusercontent.com/michaquu/ai-lot-hunter/main/search_config.json";

const LOCAL_UID_KEY = "lot_hunter_uid_v1";
const LOCAL_SWIPES_KEY = "autoswipe_swipes_v1";
const LOCAL_CONFIG_KEY = "autoswipe_search_config_v1";
const LOCAL_FIREBASE_CFG_KEY = "autoswipe_firebase_cfg_v1";

export interface FirebaseCreds {
  apiKey: string;
  projectId: string;
  databaseUrl?: string;
  appId?: string;
}

/**
 * Returns or generates a unique User ID used as the root key in the database: `/{userId}`
 */
export function getUserId(): string {
  if (typeof window !== "undefined") {
    const params = new URLSearchParams(window.location.search);
    const urlUid = params.get("uid")?.trim();
    if (urlUid) {
      localStorage.setItem(LOCAL_UID_KEY, urlUid);
      return urlUid;
    }
  }

  try {
    const existing = localStorage.getItem(LOCAL_UID_KEY)?.trim();
    if (existing) return existing;
  } catch {
    // ignore
  }

  const envUid = (import.meta.env.VITE_FIREBASE_USER_ID || "").trim();
  if (envUid) {
    try {
      localStorage.setItem(LOCAL_UID_KEY, envUid);
    } catch {
      // ignore
    }
    return envUid;
  }

  const randomPart =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID().replace(/-/g, "").slice(0, 10)
      : Math.random().toString(36).substring(2, 12);
  const newUid = `user_${randomPart}`;
  try {
    localStorage.setItem(LOCAL_UID_KEY, newUid);
  } catch {
    // ignore
  }
  return newUid;
}

export function setUserId(newUid: string): string {
  const cleaned = newUid.trim().replace(/[^a-zA-Z0-9_-]/g, "");
  if (!cleaned) return getUserId();
  localStorage.setItem(LOCAL_UID_KEY, cleaned);
  return cleaned;
}

export function getSavedFirebaseCreds(): FirebaseCreds {
  const envApiKey = import.meta.env.VITE_FIREBASE_API_KEY || "";
  const envProjectId = import.meta.env.VITE_FIREBASE_PROJECT_ID || "ai-lot-hunter";
  const envDbUrl = import.meta.env.VITE_FIREBASE_DATABASE_URL || "";
  const envAppId = import.meta.env.VITE_FIREBASE_APP_ID || "";

  try {
    const raw = localStorage.getItem(LOCAL_FIREBASE_CFG_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      return {
        apiKey: parsed.apiKey || envApiKey,
        projectId: parsed.projectId || envProjectId,
        databaseUrl: parsed.databaseUrl || envDbUrl,
        appId: parsed.appId || envAppId,
      };
    }
  } catch {
    // ignore
  }
  return {
    apiKey: envApiKey,
    projectId: envProjectId,
    databaseUrl: envDbUrl,
    appId: envAppId,
  };
}

export function saveFirebaseCreds(creds: FirebaseCreds): void {
  localStorage.setItem(LOCAL_FIREBASE_CFG_KEY, JSON.stringify(creds));
  dbInstance = null;
  resolvedRtdbUrl = creds.databaseUrl || null;
}

let dbInstance: Firestore | null = null;
let resolvedRtdbUrl: string | null = null;

/**
 * Candidate Realtime Database base URLs for the Firebase project (supports both Europe and US regions + Hosting init.json)
 */
async function getRealtimeDbBaseUrl(): Promise<string | null> {
  if (resolvedRtdbUrl) return resolvedRtdbUrl;

  const creds = getSavedFirebaseCreds();
  if (creds.databaseUrl) {
    resolvedRtdbUrl = creds.databaseUrl.replace(/\/+$/, "");
    return resolvedRtdbUrl;
  }

  // Try Firebase Hosting auto-init endpoint if running on *.web.app
  try {
    const initRes = await fetch("/__/firebase/init.json");
    if (initRes.ok) {
      const initJson = await initRes.json();
      if (initJson.databaseURL) {
        resolvedRtdbUrl = String(initJson.databaseURL).replace(/\/+$/, "");
        return resolvedRtdbUrl;
      }
    }
  } catch {
    // ignore on localhost
  }

  const pid = creds.projectId || "ai-lot-hunter";
  const candidates = [
    `https://${pid}-default-rtdb.europe-west1.firebasedatabase.app`,
    `https://${pid}-default-rtdb.firebaseio.com`,
  ];

  for (const base of candidates) {
    try {
      const probe = await fetch(`${base}/.settings/rules.json?shallow=true`, { method: "GET" });
      if (probe.status !== 404) {
        resolvedRtdbUrl = base;
        return resolvedRtdbUrl;
      }
    } catch {
      // try next
    }
  }

  resolvedRtdbUrl = candidates[0];
  return resolvedRtdbUrl;
}

export function getDb(): Firestore | null {
  if (dbInstance) return dbInstance;
  const creds = getSavedFirebaseCreds();
  if (!creds.projectId) return null;

  try {
    const existing = getApps();
    const app =
      existing.length > 0
        ? existing[0]
        : initializeApp({
            apiKey: creds.apiKey || "AIzaSyDummyKeyForFirestoreSpark",
            projectId: creds.projectId,
            authDomain: `${creds.projectId}.firebaseapp.com`,
            databaseURL:
              creds.databaseUrl || `https://${creds.projectId}-default-rtdb.europe-west1.firebasedatabase.app`,
            storageBucket: `${creds.projectId}.firebasestorage.app`,
          });
    dbInstance = getFirestore(app);
    return dbInstance;
  } catch (err) {
    console.warn("Firebase init skipped:", err);
    return null;
  }
}

export const FALLBACK_CARS: CarListing[] = [
  {
    id: "iaai_46932215",
    found_at: "2026-11-01 18:37 UTC",
    source: "IAAI",
    lot_id: "46932215",
    vin: "Sprawdź po Lot ID (46932215)",
    title: "2023 DODGE CHALLENGER SXT",
    color: "Granite Gray",
    color_approved: true,
    is_modified: false,
    modifications: "Brak (seria)",
    damage_assessment:
      "Side impact damage affecting the right front fender and passenger door, airbags intact and no major structural damage.",
    url: "https://www.iaai.com/VehicleDetail/46932215~US",
    price_check_url: "https://bid.cars/pl/lot/0-46932215",
    image_urls: [
      "https://vis.iaai.com/resizer?imageKeys=46932215~SID~I1&width=800&height=600",
      "https://vis.iaai.com/resizer?imageKeys=46932215~SID~I2&width=800&height=600",
      "https://vis.iaai.com/resizer?imageKeys=46932215~SID~I3&width=800&height=600",
      "https://vis.iaai.com/resizer?imageKeys=46932215~SID~I4&width=800&height=600",
      "https://vis.iaai.com/resizer?imageKeys=46932215~SID~I5&width=800&height=600",
      "https://vis.iaai.com/resizer?imageKeys=46932215~SID~I6&width=800&height=600",
    ],
  },
  {
    id: "copart_71903086",
    found_at: "2026-11-01 14:06 UTC",
    source: "Copart",
    lot_id: "71903086",
    vin: "Sprawdź po Lot ID (71903086)",
    title: "2019 DODGE CHALLENGER SXT",
    color: "Pitch Black",
    color_approved: true,
    is_modified: false,
    modifications: "Brak (seria)",
    damage_assessment:
      "Damage limited to bolt-on components (front bumper cover, passenger headlight, passenger front fender). Cooling pack and radiator support straight, airbags intact.",
    url: "https://www.copart.com/lot/71903086",
    price_check_url: "https://bid.cars/pl/lot/1-71903086",
    image_urls: [],
  },
];

export async function fetchPassedCars(): Promise<CarListing[]> {
  const byId = new Map<string, CarListing>();
  const userId = getUserId();

  // 1. Fetch local /passed_cars.json or GitHub passed_cars.json
  for (const url of [`/passed_cars.json?t=${Date.now()}`, `${GITHUB_PASSED_CARS_URL}?t=${Date.now()}`]) {
    try {
      const res = await fetch(url, { cache: "no-store" });
      if (res.ok) {
        const data: CarListing[] = await res.json();
        if (Array.isArray(data)) {
          for (const item of data) {
            const id = item.id || `${item.source.toLowerCase()}_${item.lot_id}`;
            byId.set(id, { ...item, id, image_urls: item.image_urls || [] });
          }
          break;
        }
      }
    } catch {
      // try next
    }
  }

  // 2. Fetch from Firebase Realtime Database (`/{userId}/cars.json` and `/cars.json`)
  try {
    const rtdbBase = await getRealtimeDbBaseUrl();
    if (rtdbBase) {
      for (const path of [`/${userId}/cars.json`, `/cars.json`]) {
        const res = await fetch(`${rtdbBase}${path}`);
        if (res.ok) {
          const data = await res.json();
          if (data && typeof data === "object") {
            for (const [k, val] of Object.entries(data)) {
              const item = val as CarListing;
              if (item && item.lot_id) {
                const id = item.id || k;
                byId.set(id, { ...item, id, image_urls: item.image_urls || [] });
              }
            }
          }
        }
      }
    }
  } catch {
    // ignore RTDB error
  }

  // 3. Also check Firestore if active
  const db = getDb();
  if (db) {
    try {
      const [userCarsSnap, globalCarsSnap] = await Promise.all([
        getDocs(collection(db, "users", userId, "cars")),
        getDocs(collection(db, "cars")),
      ]);

      for (const snap of [globalCarsSnap, userCarsSnap]) {
        snap.forEach((docSnap) => {
          const raw = docSnap.data();
          if (raw.car_json) {
            try {
              const parsed: CarListing = JSON.parse(raw.car_json);
              const id = parsed.id || docSnap.id;
              byId.set(id, { ...parsed, id, image_urls: parsed.image_urls || [] });
            } catch {
              // ignore
            }
          }
        });
      }
    } catch {
      // ignore
    }
  }

  if (byId.size === 0) {
    for (const c of FALLBACK_CARS) {
      byId.set(c.id, c);
    }
  }

  return Array.from(byId.values());
}

export function subscribeToNewCars(onCarsUpdate: (cars: CarListing[]) => void): () => void {
  const db = getDb();
  if (!db) return () => {};

  try {
    return onSnapshot(collection(db, "cars"), (snap) => {
      const cars: CarListing[] = [];
      snap.forEach((docSnap) => {
        const raw = docSnap.data();
        if (raw.car_json) {
          try {
            cars.push(JSON.parse(raw.car_json));
          } catch {
            // ignore
          }
        }
      });
      if (cars.length > 0) onCarsUpdate(cars);
    });
  } catch {
    return () => {};
  }
}

export async function loadSwipes(): Promise<Record<string, SwipeRecord>> {
  const userId = getUserId();
  let local: Record<string, SwipeRecord> = {};
  try {
    const raw = localStorage.getItem(`${LOCAL_SWIPES_KEY}_${userId}`) || localStorage.getItem(LOCAL_SWIPES_KEY);
    if (raw) local = JSON.parse(raw);
  } catch {
    local = {};
  }

  // 1. Load from Firebase Realtime Database root key: `/{userId}/swipes.json`
  try {
    const rtdbBase = await getRealtimeDbBaseUrl();
    if (rtdbBase) {
      const res = await fetch(`${rtdbBase}/${userId}/swipes.json`);
      if (res.ok) {
        const remote = await res.json();
        if (remote && typeof remote === "object") {
          const merged = { ...remote, ...local };
          localStorage.setItem(`${LOCAL_SWIPES_KEY}_${userId}`, JSON.stringify(merged));
          return merged;
        }
      }
    }
  } catch {
    // ignore
  }

  // 2. Fallback to Firestore `users/{userId}`
  const db = getDb();
  if (db) {
    try {
      const docSnap = await getDoc(doc(db, "users", userId));
      if (docSnap.exists()) {
        const data = docSnap.data();
        if (data.swipes_json) {
          const remote = JSON.parse(data.swipes_json);
          const merged = { ...remote, ...local };
          localStorage.setItem(`${LOCAL_SWIPES_KEY}_${userId}`, JSON.stringify(merged));
          return merged;
        }
      }
    } catch {
      // ignore
    }
  }
  return local;
}

export async function saveSwipes(swipes: Record<string, SwipeRecord>): Promise<void> {
  const userId = getUserId();
  localStorage.setItem(`${LOCAL_SWIPES_KEY}_${userId}`, JSON.stringify(swipes));

  // 1. Save to Firebase Realtime Database under root user key `/{userId}/swipes.json`
  try {
    const rtdbBase = await getRealtimeDbBaseUrl();
    if (rtdbBase) {
      await fetch(`${rtdbBase}/${userId}.json`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: userId,
          swipes,
          updated_at: new Date().toISOString(),
        }),
      });
    }
  } catch {
    // ignore
  }

  // 2. Also save to Firestore `users/{userId}` if active
  const db = getDb();
  if (db) {
    try {
      await setDoc(
        doc(db, "users", userId),
        {
          user_id: userId,
          swipes_json: JSON.stringify(swipes),
          updated_at: new Date().toISOString(),
        },
        { merge: true }
      );
    } catch {
      // ignore
    }
  }
}

export const DEFAULT_SEARCH_CONFIG: SearchFilterConfig = {
  use_custom_urls: true,
  make: "DODGE",
  model: "CHALLENGER",
  year_from: 2019,
  year_to: 2027,
  max_odometer: 76300,
  cylinders: "6",
  run_and_drive_only: true,
  allowed_colors: [
    "Pitch Black (Black)",
    "Granite / Destroyer / Smoke Show (Dark Gray)",
    "Plum Crazy / Hellraisin (Purple)",
  ],
  allow_modified_any_color: true,
  copart_url:
    "https://www.copart.com/lotSearchResults?free=true&query=dodge%20challenger&qId=623c1d07-ca78-4193-b4ba-028e053de722-1793537611275&index=null&searchCriteria=%7B%22query%22:%5B%22*%22%5D,%22filter%22:%7B%22FETI%22:%5B%22lot_condition_code:CERT-D%22%5D,%22PRID%22:%5B%22damage_type_code:DAMAGECODE_FR%22,%22damage_type_code:DAMAGECODE_RR%22,%22damage_type_code:DAMAGECODE_SD%22%5D,%22ODM%22:%5B%22odometer_reading_received:%5B0%20TO%2076300%5D%22%5D,%22MAKE%22:%5B%22search_lot_make_desc:%5C%22DODGE%5C%22%22%5D,%22MODL%22:%5B%22lot_model_desc:%5C%22CHALLENGER%5C%22%22%5D,%22CYLN%22:%5B%22cylinders:%5C%226%5C%22%22%5D,%22YEAR%22:%5B%22lot_year:%5B2019%20TO%202027%5D%22%5D%7D,%22sort%22:%5B%22lot_number%20desc%22%5D,%22searchName%22:%22%22,%22watchListOnly%22:false,%22freeFormSearch%22:false,%22exclusions%22:%5B%5D%7D",
  iaai_url: "https://www.iaai.com/Search?url=Tg%2fLxBEbpfSDJmuUBF%2bXu3xGxjiM2wLOeSmr8pTVcxc%3d",
};

export async function loadSearchFilterConfig(): Promise<SearchFilterConfig> {
  const userId = getUserId();

  // 1. Load from Firebase Realtime Database root key: `/{userId}/config.json`
  try {
    const rtdbBase = await getRealtimeDbBaseUrl();
    if (rtdbBase) {
      const res = await fetch(`${rtdbBase}/${userId}/config.json`);
      if (res.ok) {
        const remote = await res.json();
        if (remote && typeof remote === "object") {
          localStorage.setItem(`${LOCAL_CONFIG_KEY}_${userId}`, JSON.stringify(remote));
          return { ...DEFAULT_SEARCH_CONFIG, ...remote };
        }
      }
    }
  } catch {
    // ignore
  }

  // 2. Fallback to Firestore `users/{userId}`
  const db = getDb();
  if (db) {
    try {
      const userSnap = await getDoc(doc(db, "users", userId));
      if (userSnap.exists()) {
        const data = userSnap.data();
        if (data.config_json) {
          const parsed = JSON.parse(data.config_json);
          localStorage.setItem(`${LOCAL_CONFIG_KEY}_${userId}`, JSON.stringify(parsed));
          return { ...DEFAULT_SEARCH_CONFIG, ...parsed };
        }
      }
    } catch {
      // ignore
    }
  }

  try {
    const localRaw =
      localStorage.getItem(`${LOCAL_CONFIG_KEY}_${userId}`) || localStorage.getItem(LOCAL_CONFIG_KEY);
    if (localRaw) {
      return { ...DEFAULT_SEARCH_CONFIG, ...JSON.parse(localRaw) };
    }
  } catch {
    // ignore
  }

  try {
    const res = await fetch(`${GITHUB_SEARCH_CONFIG_URL}?t=${Date.now()}`);
    if (res.ok) {
      const remote = await res.json();
      return { ...DEFAULT_SEARCH_CONFIG, ...remote };
    }
  } catch {
    // ignore
  }

  return DEFAULT_SEARCH_CONFIG;
}

export async function saveSearchFilterConfig(cfg: SearchFilterConfig): Promise<boolean> {
  const userId = getUserId();
  localStorage.setItem(`${LOCAL_CONFIG_KEY}_${userId}`, JSON.stringify(cfg));
  let savedToCloud = false;

  // 1. Save to Firebase Realtime Database under root user key `/{userId}` and `/active_config`
  try {
    const rtdbBase = await getRealtimeDbBaseUrl();
    if (rtdbBase) {
      const [r1] = await Promise.all([
        fetch(`${rtdbBase}/${userId}.json`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            user_id: userId,
            config: cfg,
            updated_at: new Date().toISOString(),
          }),
        }),
        fetch(`${rtdbBase}/active_config.json`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            active_user_id: userId,
            config: cfg,
            updated_at: new Date().toISOString(),
          }),
        }),
      ]);
      if (r1.ok) savedToCloud = true;
    }
  } catch {
    // ignore
  }

  // 2. Also save to Firestore `users/{userId}` and `settings/scraper` if active
  const db = getDb();
  if (db) {
    try {
      await Promise.all([
        setDoc(
          doc(db, "users", userId),
          {
            user_id: userId,
            config_json: JSON.stringify(cfg),
            updated_at: new Date().toISOString(),
          },
          { merge: true }
        ),
        setDoc(
          doc(db, "settings", "scraper"),
          {
            active_user_id: userId,
            config_json: JSON.stringify(cfg),
            updated_at: new Date().toISOString(),
          },
          { merge: true }
        ),
      ]);
      savedToCloud = true;
    } catch {
      // ignore
    }
  }
  return savedToCloud;
}

export function generateCopartUrl(cfg: SearchFilterConfig): string {
  const make = cfg.make.toUpperCase().trim() || "DODGE";
  const model = cfg.model.toUpperCase().trim() || "CHALLENGER";
  const filters: Record<string, string[]> = {
    PRID: [
      "damage_type_code:DAMAGECODE_FR",
      "damage_type_code:DAMAGECODE_RR",
      "damage_type_code:DAMAGECODE_SD",
      "damage_type_code:DAMAGECODE_MN",
    ],
    ODM: [`odometer_reading_received:[0 TO ${cfg.max_odometer || 76300}]`],
    MAKE: [`search_lot_make_desc:"${make}"`],
    MODL: [`lot_model_desc:"${model}"`],
    YEAR: [`lot_year:[${cfg.year_from || 2019} TO ${cfg.year_to || 2027}]`],
  };
  if (cfg.run_and_drive_only) {
    filters.FETI = ["lot_condition_code:CERT-D"];
  }
  if (cfg.cylinders && cfg.cylinders !== "ALL") {
    filters.CYLN = [`cylinders:"${cfg.cylinders}"`];
  }
  const criteria = {
    query: ["*"],
    filter: filters,
    sort: ["lot_number desc"],
    searchName: "",
    watchListOnly: false,
    freeFormSearch: false,
    exclusions: [],
  };
  const q = encodeURIComponent(`${make.toLowerCase()} ${model.toLowerCase()}`);
  const sc = encodeURIComponent(JSON.stringify(criteria));
  return `https://www.copart.com/lotSearchResults?free=true&query=${q}&index=null&searchCriteria=${sc}`;
}

export function generateIaaiUrl(cfg: SearchFilterConfig): string {
  const q = encodeURIComponent(`${cfg.make.trim()} ${cfg.model.trim()}`);
  return `https://www.iaai.com/Search?keyword=${q}`;
}
