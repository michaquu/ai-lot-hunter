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
  "https://raw.githubusercontent.com/michaquu/copart-ai-scraper/main/passed_cars.json";
const GITHUB_SEARCH_CONFIG_URL =
  "https://raw.githubusercontent.com/michaquu/copart-ai-scraper/main/search_config.json";

const LOCAL_SWIPES_KEY = "autoswipe_swipes_v1";
const LOCAL_CONFIG_KEY = "autoswipe_search_config_v1";
const LOCAL_FIREBASE_CFG_KEY = "autoswipe_firebase_cfg_v1";

export interface FirebaseCreds {
  apiKey: string;
  projectId: string;
  appId?: string;
}

export function getSavedFirebaseCreds(): FirebaseCreds {
  try {
    const raw = localStorage.getItem(LOCAL_FIREBASE_CFG_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (parsed.projectId) return parsed;
    }
  } catch {
    // ignore
  }
  return {
    apiKey: import.meta.env.VITE_FIREBASE_API_KEY || "",
    projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID || "",
    appId: import.meta.env.VITE_FIREBASE_APP_ID || "",
  };
}

export function saveFirebaseCreds(creds: FirebaseCreds): void {
  localStorage.setItem(LOCAL_FIREBASE_CFG_KEY, JSON.stringify(creds));
}

let dbInstance: Firestore | null = null;

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
    price_check_url: "https://bid.cars/pl/search/results?search-type=filters&q=46932215",
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
    price_check_url: "https://bid.cars/pl/search/results?search-type=filters&q=71903086",
    image_urls: [],
  },
];

export async function fetchPassedCars(): Promise<CarListing[]> {
  const byId = new Map<string, CarListing>();

  // 1. Fetch live passed_cars.json from GitHub repository
  try {
    const res = await fetch(`${GITHUB_PASSED_CARS_URL}?t=${Date.now()}`, {
      cache: "no-store",
    });
    if (res.ok) {
      const data: CarListing[] = await res.json();
      if (Array.isArray(data)) {
        for (const item of data) {
          const id = item.id || `${item.source.toLowerCase()}_${item.lot_id}`;
          byId.set(id, { ...item, id, image_urls: item.image_urls || [] });
        }
      }
    }
  } catch (err) {
    console.warn("GitHub passed_cars.json fetch fallback:", err);
  }

  // 2. Also fetch from Firebase Firestore 'cars' collection if connected
  const db = getDb();
  if (db) {
    try {
      const snap = await getDocs(collection(db, "cars"));
      snap.forEach((docSnap) => {
        const raw = docSnap.data();
        if (raw.car_json) {
          try {
            const parsed: CarListing = JSON.parse(raw.car_json);
            const id = parsed.id || docSnap.id;
            byId.set(id, { ...parsed, id, image_urls: parsed.image_urls || [] });
          } catch {
            // ignore malformed
          }
        }
      });
    } catch (err) {
      console.warn("Firestore cars fetch skipped:", err);
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
      if (cars.length > 0) {
        onCarsUpdate(cars);
      }
    });
  } catch {
    return () => {};
  }
}

export async function loadSwipes(): Promise<Record<string, SwipeRecord>> {
  let local: Record<string, SwipeRecord> = {};
  try {
    const raw = localStorage.getItem(LOCAL_SWIPES_KEY);
    if (raw) local = JSON.parse(raw);
  } catch {
    local = {};
  }

  const db = getDb();
  if (db) {
    try {
      const docSnap = await getDoc(doc(db, "user_state", "swipes"));
      if (docSnap.exists()) {
        const data = docSnap.data();
        if (data.swipes_json) {
          const remote = JSON.parse(data.swipes_json);
          const merged = { ...remote, ...local };
          localStorage.setItem(LOCAL_SWIPES_KEY, JSON.stringify(merged));
          return merged;
        }
      }
    } catch (err) {
      console.warn("Firestore swipes load skipped:", err);
    }
  }
  return local;
}

export async function saveSwipes(swipes: Record<string, SwipeRecord>): Promise<void> {
  localStorage.setItem(LOCAL_SWIPES_KEY, JSON.stringify(swipes));
  const db = getDb();
  if (db) {
    try {
      await setDoc(
        doc(db, "user_state", "swipes"),
        {
          swipes_json: JSON.stringify(swipes),
          updated_at: new Date().toISOString(),
        },
        { merge: true }
      );
    } catch (err) {
      console.warn("Firestore swipes save skipped:", err);
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
  const db = getDb();
  if (db) {
    try {
      const docSnap = await getDoc(doc(db, "settings", "scraper"));
      if (docSnap.exists()) {
        const data = docSnap.data();
        if (data.config_json) {
          const parsed = JSON.parse(data.config_json);
          localStorage.setItem(LOCAL_CONFIG_KEY, JSON.stringify(parsed));
          return { ...DEFAULT_SEARCH_CONFIG, ...parsed };
        }
      }
    } catch {
      // ignore
    }
  }

  try {
    const localRaw = localStorage.getItem(LOCAL_CONFIG_KEY);
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
  localStorage.setItem(LOCAL_CONFIG_KEY, JSON.stringify(cfg));
  const db = getDb();
  if (db) {
    try {
      await setDoc(
        doc(db, "settings", "scraper"),
        {
          config_json: JSON.stringify(cfg),
          updated_at: new Date().toISOString(),
        },
        { merge: true }
      );
      return true;
    } catch (err) {
      console.error("Failed to save config to Firestore:", err);
      return false;
    }
  }
  return false;
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
