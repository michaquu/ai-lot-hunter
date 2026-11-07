import React, { useEffect, useState, useRef } from "react";
import {
  Flame,
  Heart,
  Archive,
  SlidersHorizontal,
  ExternalLink,
  DollarSign,
  RotateCcw,
  X,
  Check,
  Sparkles,
  Copy,
  Bell,
  RefreshCw,
  ChevronLeft,
  ChevronRight,
  Database,
  Car,
} from "lucide-react";
import { CarListing, SearchFilterConfig, SwipeDecision, SwipeRecord } from "./types";
import {
  fetchPassedCars,
  loadSwipes,
  saveSwipes,
  loadSearchFilterConfig,
  saveSearchFilterConfig,
  generateCopartUrl,
  generateIaaiUrl,
  getSavedFirebaseCreds,
  saveFirebaseCreds,
  subscribeToNewCars,
} from "./firebase";

type ActiveTab = "swipe" | "liked" | "archived" | "settings";

const COLOR_OPTIONS = [
  "Pitch Black (Black)",
  "Granite / Destroyer / Smoke Show (Dark Gray)",
  "Plum Crazy / Hellraisin (Purple)",
  "White Knuckle (White)",
  "TorRed / Octane Red (Red)",
  "Frostbite / Indigo (Blue)",
  "F8 Green / Sublime (Green)",
];

const CAR_PRESETS = [
  { label: "Dodge Challenger", make: "DODGE", model: "CHALLENGER", cyl: "6" },
  { label: "Dodge Charger", make: "DODGE", model: "CHARGER", cyl: "6" },
  { label: "Ford Mustang", make: "FORD", model: "MUSTANG", cyl: "ALL" },
  { label: "Chevrolet Camaro", make: "CHEVROLET", model: "CAMARO", cyl: "ALL" },
];

export default function App() {
  const [activeTab, setActiveTab] = useState<ActiveTab>("swipe");
  const [cars, setCars] = useState<CarListing[]>([]);
  const [swipes, setSwipes] = useState<Record<string, SwipeRecord>>({});
  const [historyStack, setHistoryStack] = useState<string[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [photoIdx, setPhotoIdx] = useState<number>(0);
  const [copiedText, setCopiedText] = useState<string | null>(null);
  const [notifEnabled, setNotifEnabled] = useState<boolean>(
    typeof Notification !== "undefined" && Notification.permission === "granted"
  );

  // Drag / swipe gesture state
  const [dragX, setDragX] = useState<number>(0);
  const [isDragging, setIsDragging] = useState<boolean>(false);
  const dragStartX = useRef<number | null>(null);

  // Filter & Firebase Settings state
  const [filterCfg, setFilterCfg] = useState<SearchFilterConfig | null>(null);
  const [fbProjectId, setFbProjectId] = useState<string>(getSavedFirebaseCreds().projectId);
  const [fbApiKey, setFbApiKey] = useState<string>(getSavedFirebaseCreds().apiKey);
  const [saveBanner, setSaveBanner] = useState<string | null>(null);

  const knownCarIdsRef = useRef<Set<string>>(new Set());

  const triggerBrowserNotification = async (car: CarListing) => {
    if (typeof Notification === "undefined" || Notification.permission !== "granted") return;
    try {
      const reg = await navigator.serviceWorker?.getRegistration();
      const title = `🚨 Nowe auto (PASS): ${car.title}`;
      const body = `${car.source} #${car.lot_id} • ${car.color}${
        car.is_modified ? ` • 🔥 ${car.modifications}` : ""
      }`;
      if (reg && "showNotification" in reg) {
        await reg.showNotification(title, {
          body,
          icon: "/icon.svg",
          data: { url: window.location.origin },
        });
      } else {
        new Notification(title, { body, icon: "/icon.svg" });
      }
    } catch {
      // ignore
    }
  };

  const refreshData = async (silent = false) => {
    if (!silent) setLoading(true);
    const [loadedCars, loadedSwipes, loadedCfg] = await Promise.all([
      fetchPassedCars(),
      loadSwipes(),
      loadSearchFilterConfig(),
    ]);

    // Check if any brand-new car arrived for notification
    if (knownCarIdsRef.current.size > 0) {
      for (const c of loadedCars) {
        if (!knownCarIdsRef.current.has(c.id)) {
          triggerBrowserNotification(c);
        }
      }
    }
    knownCarIdsRef.current = new Set(loadedCars.map((c) => c.id));

    setCars(loadedCars);
    setSwipes(loadedSwipes);
    setFilterCfg((prev) => prev || loadedCfg);
    if (!silent) setLoading(false);
  };

  useEffect(() => {
    refreshData();

    // Subscribe to real-time Firestore updates if configured
    const unsub = subscribeToNewCars((remoteCars) => {
      setCars((prev) => {
        const map = new Map(prev.map((c) => [c.id, c]));
        for (const rc of remoteCars) {
          if (!knownCarIdsRef.current.has(rc.id)) {
            knownCarIdsRef.current.add(rc.id);
            triggerBrowserNotification(rc);
          }
          map.set(rc.id, rc);
        }
        return Array.from(map.values());
      });
    });

    // Poll GitHub passed_cars.json every 5 minutes for new GitHub Action runs
    const interval = setInterval(() => refreshData(true), 5 * 60 * 1000);
    return () => {
      unsub();
      clearInterval(interval);
    };
  }, []);

  const unswipedCars = cars.filter((c) => !swipes[c.id]);
  const likedCars = cars.filter((c) => swipes[c.id]?.decision === "liked");
  const archivedCars = cars.filter((c) => swipes[c.id]?.decision === "archived");
  const currentCar = unswipedCars[0] || null;

  useEffect(() => {
    setPhotoIdx(0);
    setDragX(0);
  }, [currentCar?.id]);

  const handleDecision = async (carId: string, decision: SwipeDecision) => {
    const updated: Record<string, SwipeRecord> = {
      ...swipes,
      [carId]: {
        carId,
        decision,
        swipedAt: new Date().toISOString(),
        note: swipes[carId]?.note || "",
      },
    };
    setHistoryStack((prev) => [...prev, carId]);
    setSwipes(updated);
    setDragX(0);
    await saveSwipes(updated);
  };

  const handleUndo = async () => {
    if (historyStack.length === 0) return;
    const lastId = historyStack[historyStack.length - 1];
    const updated = { ...swipes };
    delete updated[lastId];
    setHistoryStack((prev) => prev.slice(0, -1));
    setSwipes(updated);
    await saveSwipes(updated);
  };

  const handleRestoreToDeck = async (carId: string) => {
    const updated = { ...swipes };
    delete updated[carId];
    setSwipes(updated);
    await saveSwipes(updated);
  };

  const handleNoteChange = async (carId: string, note: string) => {
    if (!swipes[carId]) return;
    const updated = {
      ...swipes,
      [carId]: { ...swipes[carId], note },
    };
    setSwipes(updated);
    await saveSwipes(updated);
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedText(text);
    setTimeout(() => setCopiedText(null), 1800);
  };

  const requestNotifications = async () => {
    if (typeof Notification === "undefined") return;
    const perm = await Notification.requestPermission();
    setNotifEnabled(perm === "granted");
    if (perm === "granted" && cars[0]) {
      triggerBrowserNotification(cars[0]);
    }
  };

  // Pointer drag handlers for Tinder card
  const onPointerDown = (e: React.PointerEvent) => {
    dragStartX.current = e.clientX;
    setIsDragging(true);
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!isDragging || dragStartX.current === null) return;
    setDragX(e.clientX - dragStartX.current);
  };

  const onPointerUp = () => {
    if (!isDragging) return;
    setIsDragging(false);
    dragStartX.current = null;
    if (!currentCar) return;

    if (dragX > 110) {
      handleDecision(currentCar.id, "liked");
    } else if (dragX < -110) {
      handleDecision(currentCar.id, "archived");
    } else {
      setDragX(0);
    }
  };

  const getCarImages = (car: CarListing): string[] => {
    if (car.image_urls && car.image_urls.length > 0) return car.image_urls;
    if (car.source.toLowerCase() === "iaai") {
      return [1, 2, 3, 4, 5, 6].map(
        (i) => `https://vis.iaai.com/resizer?imageKeys=${car.lot_id}~SID~I${i}&width=800&height=600`
      );
    }
    return [];
  };

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 flex flex-col max-w-md mx-auto border-x border-zinc-900 shadow-2xl">
      {/* Top Header */}
      <header className="px-4 py-3 border-b border-zinc-900 flex items-center justify-between bg-zinc-950/90 backdrop-blur sticky top-0 z-30">
        <div className="flex items-center gap-2.5">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-violet-600 to-fuchsia-600 flex items-center justify-center shadow-lg shadow-violet-600/30">
            <Flame className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="font-bold text-base leading-none tracking-tight flex items-center gap-1.5">
              AutoSwipe <span className="text-xs px-1.5 py-0.5 rounded bg-violet-500/20 text-violet-300 font-semibold">AI</span>
            </h1>
            <p className="text-[11px] text-zinc-400 mt-0.5">
              Copart & IAAI • Do oceny: <strong className="text-zinc-200">{unswipedCars.length}</strong>
            </p>
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            onClick={requestNotifications}
            title={notifEnabled ? "Powiadomienia włączone" : "Włącz powiadomienia o nowych autach"}
            className={`p-2 rounded-xl border transition ${
              notifEnabled
                ? "bg-emerald-500/15 border-emerald-500/40 text-emerald-400"
                : "bg-zinc-900 border-zinc-800 text-zinc-400 hover:text-zinc-200"
            }`}
          >
            <Bell className="w-4 h-4" />
          </button>
          <button
            onClick={() => refreshData(false)}
            title="Odśwież listę aut z GitHub / Firebase"
            className="p-2 rounded-xl bg-zinc-900 border border-zinc-800 text-zinc-300 hover:text-white active:scale-95 transition"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin text-violet-400" : ""}`} />
          </button>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="flex-1 overflow-y-auto p-4 pb-24">
        {/* TAB 1: TINDER SWIPE DECK */}
        {activeTab === "swipe" && (
          <div className="flex flex-col h-full">
            {loading ? (
              <div className="flex-1 flex flex-col items-center justify-center py-20 text-zinc-400 gap-3">
                <RefreshCw className="w-8 h-8 animate-spin text-violet-500" />
                <p className="text-sm">Pobieranie zaakceptowanych aut (PASS)...</p>
              </div>
            ) : !currentCar ? (
              <div className="flex-1 flex flex-col items-center justify-center py-16 text-center px-4">
                <div className="w-16 h-16 rounded-2xl bg-zinc-900 border border-zinc-800 flex items-center justify-center mb-4 text-violet-400">
                  <Sparkles className="w-8 h-8" />
                </div>
                <h2 className="text-lg font-bold text-zinc-100">Wszystkie auta ocenione!</h2>
                <p className="text-xs text-zinc-400 mt-1 max-w-xs">
                  Gdy GitHub Actions znajdzie kolejne auto ze statusem PASS, pojawi się tutaj automatycznie.
                </p>
                <div className="flex flex-wrap gap-2 mt-6 justify-center">
                  {historyStack.length > 0 && (
                    <button
                      onClick={handleUndo}
                      className="px-4 py-2.5 rounded-xl bg-zinc-900 border border-zinc-800 text-xs font-semibold flex items-center gap-1.5 hover:bg-zinc-800"
                    >
                      <RotateCcw className="w-4 h-4 text-amber-400" /> Cofnij ostatni swipe
                    </button>
                  )}
                  <button
                    onClick={() => setActiveTab("liked")}
                    className="px-4 py-2.5 rounded-xl bg-violet-600 text-white text-xs font-semibold flex items-center gap-1.5 hover:bg-violet-500"
                  >
                    <Heart className="w-4 h-4" /> Zobacz Ulubione ({likedCars.length})
                  </button>
                </div>
              </div>
            ) : (
              (() => {
                const imgs = getCarImages(currentCar);
                const activeImg = imgs[photoIdx] || "";
                const rotateDeg = Math.max(-14, Math.min(14, dragX * 0.06));

                return (
                  <div className="flex flex-col gap-3">
                    {/* Swipeable Card */}
                    <div
                      onPointerDown={onPointerDown}
                      onPointerMove={onPointerMove}
                      onPointerUp={onPointerUp}
                      onPointerCancel={onPointerUp}
                      style={{
                        transform: `translateX(${dragX}px) rotate(${rotateDeg}deg)`,
                        transition: isDragging ? "none" : "transform 0.25s cubic-bezier(0.2, 0.8, 0.2, 1)",
                      }}
                      className="relative rounded-3xl bg-zinc-900 border border-zinc-800 overflow-hidden shadow-2xl touch-pan-y select-none cursor-grab active:cursor-grabbing"
                    >
                      {/* Swipe Stamps */}
                      {dragX > 45 && (
                        <div className="absolute top-6 left-6 z-20 px-4 py-1.5 rounded-xl border-4 border-emerald-400 text-emerald-400 font-black text-xl tracking-wider -rotate-12 bg-zinc-950/70 backdrop-blur">
                          ULUBIONE ❤️
                        </div>
                      )}
                      {dragX < -45 && (
                        <div className="absolute top-6 right-6 z-20 px-4 py-1.5 rounded-xl border-4 border-rose-500 text-rose-500 font-black text-xl tracking-wider rotate-12 bg-zinc-950/70 backdrop-blur">
                          SCHOWEK 📁
                        </div>
                      )}

                      {/* Photo Carousel */}
                      <div className="relative h-72 bg-zinc-950 flex items-center justify-center overflow-hidden">
                        {activeImg ? (
                          <img
                            src={activeImg}
                            alt={currentCar.title}
                            draggable={false}
                            className="w-full h-full object-cover"
                          />
                        ) : (
                          <div className="flex flex-col items-center justify-center text-zinc-500 gap-2 p-6 text-center">
                            <Car className="w-12 h-12 text-zinc-600" />
                            <span className="text-xs">
                              Zdjęcia dostępne bezpośrednio na stronie {currentCar.source} (#{currentCar.lot_id})
                            </span>
                          </div>
                        )}

                        {/* Source & Date Badges */}
                        <div className="absolute top-3 left-3 right-3 flex items-center justify-between pointer-events-none">
                          <span
                            className={`px-2.5 py-1 rounded-lg text-xs font-bold shadow-md backdrop-blur ${
                              currentCar.source.toLowerCase() === "copart"
                                ? "bg-blue-600/90 text-white"
                                : "bg-amber-500/90 text-zinc-950"
                            }`}
                          >
                            {currentCar.source.toUpperCase()} #{currentCar.lot_id}
                          </span>
                          <span className="px-2.5 py-1 rounded-lg text-[11px] font-medium bg-zinc-950/80 text-zinc-300 backdrop-blur">
                            {currentCar.found_at}
                          </span>
                        </div>

                        {/* Prev / Next Photo Controls */}
                        {imgs.length > 1 && (
                          <>
                            <button
                              type="button"
                              onPointerDown={(e) => e.stopPropagation()}
                              onClick={() => setPhotoIdx((prev) => (prev - 1 + imgs.length) % imgs.length)}
                              className="absolute left-2 top-1/2 -translate-y-1/2 w-8 h-8 rounded-full bg-zinc-950/70 text-white flex items-center justify-center hover:bg-zinc-950"
                            >
                              <ChevronLeft className="w-5 h-5" />
                            </button>
                            <button
                              type="button"
                              onPointerDown={(e) => e.stopPropagation()}
                              onClick={() => setPhotoIdx((prev) => (prev + 1) % imgs.length)}
                              className="absolute right-2 top-1/2 -translate-y-1/2 w-8 h-8 rounded-full bg-zinc-950/70 text-white flex items-center justify-center hover:bg-zinc-950"
                            >
                              <ChevronRight className="w-5 h-5" />
                            </button>
                            <div className="absolute bottom-2.5 left-0 right-0 flex justify-center gap-1.5">
                              {imgs.map((_, idx) => (
                                <span
                                  key={idx}
                                  className={`h-1.5 rounded-full transition-all ${
                                    idx === photoIdx ? "w-5 bg-white" : "w-1.5 bg-white/40"
                                  }`}
                                />
                              ))}
                            </div>
                          </>
                        )}
                      </div>

                      {/* Card Details */}
                      <div className="p-4 space-y-3">
                        <div>
                          <h2 className="text-lg font-extrabold text-white leading-snug">
                            {currentCar.title}
                          </h2>
                          <div className="flex flex-wrap items-center gap-1.5 mt-1.5">
                            <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-zinc-800 text-zinc-200 border border-zinc-700">
                              🎨 {currentCar.color}
                            </span>
                            {currentCar.is_modified && (
                              <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-fuchsia-500/20 text-fuchsia-300 border border-fuchsia-500/40 flex items-center gap-1">
                                <Sparkles className="w-3 h-3" /> Tuning / Przeróbki
                              </span>
                            )}
                          </div>
                        </div>

                        {/* VIN Bar */}
                        <div className="flex items-center justify-between px-3 py-2 rounded-xl bg-zinc-950 border border-zinc-800/80 text-xs">
                          <div>
                            <span className="text-zinc-500 mr-1.5">VIN:</span>
                            <code className="font-mono font-bold text-zinc-200">{currentCar.vin}</code>
                          </div>
                          <button
                            type="button"
                            onPointerDown={(e) => e.stopPropagation()}
                            onClick={() => copyToClipboard(currentCar.vin.includes(" ") ? currentCar.lot_id : currentCar.vin)}
                            className="text-violet-400 hover:text-violet-300 flex items-center gap-1 font-medium"
                          >
                            <Copy className="w-3.5 h-3.5" />
                            {copiedText ? "Skopiowano!" : "Kopiuj"}
                          </button>
                        </div>

                        {/* Modifications Info if present */}
                        {currentCar.is_modified && (
                          <div className="p-2.5 rounded-xl bg-fuchsia-950/30 border border-fuchsia-800/40 text-xs text-fuchsia-200">
                            <strong className="font-semibold">🔥 Wykryte przeróbki:</strong> {currentCar.modifications}
                          </div>
                        )}

                        {/* AI Damage Assessment */}
                        <div className="p-3 rounded-xl bg-zinc-950/60 border border-zinc-800/80 text-xs text-zinc-300 leading-relaxed">
                          <span className="text-emerald-400 font-semibold block mb-0.5">
                            ✅ Ocena uszkodzeń AI (PASS):
                          </span>
                          {currentCar.damage_assessment}
                        </div>

                        {/* Quick External Links */}
                        <div className="grid grid-cols-2 gap-2 pt-1">
                          <a
                            href={currentCar.url}
                            target="_blank"
                            rel="noreferrer"
                            onPointerDown={(e) => e.stopPropagation()}
                            className="py-2.5 px-3 rounded-xl bg-zinc-800 hover:bg-zinc-700 text-xs font-semibold text-center flex items-center justify-center gap-1.5 transition"
                          >
                            <ExternalLink className="w-3.5 h-3.5" /> Otwórz {currentCar.source}
                          </a>
                          <a
                            href={currentCar.price_check_url}
                            target="_blank"
                            rel="noreferrer"
                            onPointerDown={(e) => e.stopPropagation()}
                            className="py-2.5 px-3 rounded-xl bg-amber-500/15 hover:bg-amber-500/25 border border-amber-500/30 text-amber-300 text-xs font-semibold text-center flex items-center justify-center gap-1.5 transition"
                          >
                            <DollarSign className="w-3.5 h-3.5" /> Sprawdź w Bid.Cars
                          </a>
                        </div>
                      </div>
                    </div>

                    {/* Tinder Action Buttons */}
                    <div className="flex items-center justify-center gap-4 pt-2">
                      <button
                        onClick={handleUndo}
                        disabled={historyStack.length === 0}
                        title="Cofnij ostatni ruch"
                        className="w-12 h-12 rounded-full bg-zinc-900 border border-zinc-800 flex items-center justify-center text-amber-400 disabled:opacity-30 hover:bg-zinc-800 active:scale-90 transition shadow-lg"
                      >
                        <RotateCcw className="w-5 h-5" />
                      </button>

                      <button
                        onClick={() => handleDecision(currentCar.id, "archived")}
                        title="W lewo -> Do Schowka"
                        className="w-16 h-16 rounded-full bg-zinc-900 border-2 border-rose-500/60 flex items-center justify-center text-rose-500 hover:bg-rose-500 hover:text-white active:scale-90 transition shadow-xl shadow-rose-500/10"
                      >
                        <X className="w-8 h-8 stroke-[2.5]" />
                      </button>

                      <button
                        onClick={() => handleDecision(currentCar.id, "liked")}
                        title="W prawo -> Do Ulubionych"
                        className="w-16 h-16 rounded-full bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center text-white hover:opacity-95 active:scale-90 transition shadow-xl shadow-emerald-500/25"
                      >
                        <Heart className="w-8 h-8 fill-white" />
                      </button>
                    </div>
                  </div>
                );
              })()
            )}
          </div>
        )}

        {/* TAB 2: LIKED / ULUBIONE */}
        {activeTab === "liked" && (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-bold flex items-center gap-2">
                <Heart className="w-4 h-4 text-emerald-400 fill-emerald-400" />
                Ulubione auta ({likedCars.length})
              </h2>
              {likedCars.length > 0 && (
                <a
                  href="https://bid.cars/pl/search/results?search-type=filters&q=Dodge+Challenger"
                  target="_blank"
                  rel="noreferrer"
                  className="text-xs text-amber-400 hover:underline flex items-center gap-1 font-medium"
                >
                  <DollarSign className="w-3.5 h-3.5" /> Otwórz Bid.Cars
                </a>
              )}
            </div>

            {likedCars.length === 0 ? (
              <div className="p-8 rounded-2xl bg-zinc-900/50 border border-zinc-800 text-center text-xs text-zinc-400">
                Przesuń kartę w prawo (lub kliknij zielone serce), aby dodać auto do Ulubionych.
              </div>
            ) : (
              likedCars.map((car) => {
                const imgs = getCarImages(car);
                return (
                  <div
                    key={car.id}
                    className="rounded-2xl bg-zinc-900 border border-zinc-800 overflow-hidden shadow-md"
                  >
                    <div className="flex gap-3 p-3">
                      <div className="w-28 h-24 rounded-xl bg-zinc-950 overflow-hidden shrink-0 flex items-center justify-center">
                        {imgs[0] ? (
                          <img src={imgs[0]} alt={car.title} className="w-full h-full object-cover" />
                        ) : (
                          <Car className="w-8 h-8 text-zinc-700" />
                        )}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between gap-1">
                          <span className="text-[11px] font-bold text-violet-400">
                            {car.source} #{car.lot_id}
                          </span>
                          <span className="text-[10px] text-zinc-500">{car.found_at}</span>
                        </div>
                        <h3 className="font-bold text-sm text-white truncate">{car.title}</h3>
                        <p className="text-xs text-zinc-400 mt-0.5">
                          🎨 {car.color} {car.is_modified ? `• 🔥 ${car.modifications}` : ""}
                        </p>
                        <div className="flex items-center gap-2 mt-1">
                          <code className="text-[11px] font-mono text-zinc-300 bg-zinc-950 px-1.5 py-0.5 rounded">
                            VIN: {car.vin}
                          </code>
                        </div>
                      </div>
                    </div>

                    <div className="px-3 pb-3 space-y-2">
                      <input
                        type="text"
                        placeholder="Notatka (np. max oferta $6500, data aukcji)..."
                        value={swipes[car.id]?.note || ""}
                        onChange={(e) => handleNoteChange(car.id, e.target.value)}
                        className="w-full px-3 py-1.5 rounded-xl bg-zinc-950 border border-zinc-800 text-xs text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-violet-500"
                      />
                      <div className="flex items-center gap-2">
                        <a
                          href={car.url}
                          target="_blank"
                          rel="noreferrer"
                          className="flex-1 py-2 rounded-xl bg-zinc-800 hover:bg-zinc-700 text-xs font-semibold text-center flex items-center justify-center gap-1"
                        >
                          <ExternalLink className="w-3.5 h-3.5" /> Aukcja
                        </a>
                        <a
                          href={car.price_check_url}
                          target="_blank"
                          rel="noreferrer"
                          className="flex-1 py-2 rounded-xl bg-amber-500/20 border border-amber-500/40 text-amber-300 text-xs font-semibold text-center flex items-center justify-center gap-1"
                        >
                          <DollarSign className="w-3.5 h-3.5" /> Cena w Bid.Cars
                        </a>
                        <button
                          onClick={() => handleDecision(car.id, "archived")}
                          title="Przenieś do Schowka"
                          className="p-2 rounded-xl bg-zinc-800 text-zinc-400 hover:text-rose-400"
                        >
                          <Archive className="w-4 h-4" />
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        )}

        {/* TAB 3: ARCHIVED / SCHOWEK (SWIPED LEFT) */}
        {activeTab === "archived" && (
          <div className="space-y-3">
            <h2 className="text-base font-bold flex items-center gap-2">
              <Archive className="w-4 h-4 text-rose-400" />
              Schowek — przesunięte w lewo ({archivedCars.length})
            </h2>

            {archivedCars.length === 0 ? (
              <div className="p-8 rounded-2xl bg-zinc-900/50 border border-zinc-800 text-center text-xs text-zinc-400">
                Auta odrzucone w lewo trafiają tutaj do Schowka — zawsze możesz sprawdzić ich cenę w Bid.Cars lub przywrócić je do Ulubionych.
              </div>
            ) : (
              archivedCars.map((car) => {
                const imgs = getCarImages(car);
                return (
                  <div
                    key={car.id}
                    className="rounded-2xl bg-zinc-900/70 border border-zinc-800/80 p-3 space-y-2.5"
                  >
                    <div className="flex gap-3">
                      <div className="w-20 h-16 rounded-xl bg-zinc-950 overflow-hidden shrink-0 flex items-center justify-center">
                        {imgs[0] ? (
                          <img src={imgs[0]} alt={car.title} className="w-full h-full object-cover opacity-80" />
                        ) : (
                          <Car className="w-6 h-6 text-zinc-700" />
                        )}
                      </div>
                      <div className="flex-1 min-w-0">
                        <span className="text-[11px] font-semibold text-zinc-400">
                          {car.source} #{car.lot_id} • {car.color}
                        </span>
                        <h3 className="font-bold text-sm text-zinc-200 truncate">{car.title}</h3>
                        <code className="text-[11px] font-mono text-zinc-400">VIN: {car.vin}</code>
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      <a
                        href={car.price_check_url}
                        target="_blank"
                        rel="noreferrer"
                        className="flex-1 py-1.5 rounded-xl bg-amber-500/15 border border-amber-500/30 text-amber-300 text-xs font-semibold text-center flex items-center justify-center gap-1"
                      >
                        <DollarSign className="w-3.5 h-3.5" /> Sprawdź w Bid.Cars
                      </a>
                      <button
                        onClick={() => handleDecision(car.id, "liked")}
                        className="px-3 py-1.5 rounded-xl bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 text-xs font-semibold flex items-center gap-1"
                      >
                        <Heart className="w-3.5 h-3.5" /> Do Ulubionych
                      </button>
                      <button
                        onClick={() => handleRestoreToDeck(car.id)}
                        title="Przywróć na ekran swipe'owania"
                        className="p-1.5 rounded-xl bg-zinc-800 text-zinc-300 hover:text-white"
                      >
                        <RotateCcw className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        )}

        {/* TAB 4: SETTINGS & FILTER BUILDER */}
        {activeTab === "settings" && filterCfg && (
          <div className="space-y-4">
            {saveBanner && (
              <div className="p-3 rounded-xl bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 text-xs font-semibold flex items-center gap-2">
                <Check className="w-4 h-4" /> {saveBanner}
              </div>
            )}

            {/* Mode Switch: Filter Builder vs Custom URLs */}
            <div className="p-4 rounded-2xl bg-zinc-900 border border-zinc-800 space-y-3">
              <h2 className="text-sm font-bold flex items-center gap-2 text-white">
                <SlidersHorizontal className="w-4 h-4 text-violet-400" />
                Konfiguracja szukanego auta i filtrów
              </h2>

              <div className="grid grid-cols-2 gap-2 p-1 bg-zinc-950 rounded-xl border border-zinc-800">
                <button
                  type="button"
                  onClick={() => setFilterCfg({ ...filterCfg, use_custom_urls: false })}
                  className={`py-2 rounded-lg text-xs font-semibold transition ${
                    !filterCfg.use_custom_urls
                      ? "bg-violet-600 text-white"
                      : "text-zinc-400 hover:text-zinc-200"
                  }`}
                >
                  Kreator filtrów (Auto-URL)
                </button>
                <button
                  type="button"
                  onClick={() => setFilterCfg({ ...filterCfg, use_custom_urls: true })}
                  className={`py-2 rounded-lg text-xs font-semibold transition ${
                    filterCfg.use_custom_urls
                      ? "bg-violet-600 text-white"
                      : "text-zinc-400 hover:text-zinc-200"
                  }`}
                >
                  Własne linki Copart / IAAI
                </button>
              </div>

              {!filterCfg.use_custom_urls ? (
                <div className="space-y-3 pt-1">
                  <div>
                    <label className="text-[11px] text-zinc-400 block mb-1">Szybki wybór modelu:</label>
                    <div className="flex flex-wrap gap-1.5">
                      {CAR_PRESETS.map((p) => (
                        <button
                          key={p.label}
                          type="button"
                          onClick={() =>
                            setFilterCfg({
                              ...filterCfg,
                              make: p.make,
                              model: p.model,
                              cylinders: p.cyl,
                            })
                          }
                          className="px-2.5 py-1 rounded-lg bg-zinc-950 border border-zinc-800 text-xs hover:border-violet-500"
                        >
                          {p.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="text-[11px] text-zinc-400 block mb-1">Marka (Make)</label>
                      <input
                        type="text"
                        value={filterCfg.make}
                        onChange={(e) => setFilterCfg({ ...filterCfg, make: e.target.value })}
                        className="w-full px-3 py-2 rounded-xl bg-zinc-950 border border-zinc-800 text-xs"
                      />
                    </div>
                    <div>
                      <label className="text-[11px] text-zinc-400 block mb-1">Model</label>
                      <input
                        type="text"
                        value={filterCfg.model}
                        onChange={(e) => setFilterCfg({ ...filterCfg, model: e.target.value })}
                        className="w-full px-3 py-2 rounded-xl bg-zinc-950 border border-zinc-800 text-xs"
                      />
                    </div>
                  </div>

                  <div className="grid grid-cols-3 gap-2">
                    <div>
                      <label className="text-[11px] text-zinc-400 block mb-1">Rocznik Od</label>
                      <input
                        type="number"
                        value={filterCfg.year_from}
                        onChange={(e) => setFilterCfg({ ...filterCfg, year_from: Number(e.target.value) })}
                        className="w-full px-3 py-2 rounded-xl bg-zinc-950 border border-zinc-800 text-xs"
                      />
                    </div>
                    <div>
                      <label className="text-[11px] text-zinc-400 block mb-1">Rocznik Do</label>
                      <input
                        type="number"
                        value={filterCfg.year_to}
                        onChange={(e) => setFilterCfg({ ...filterCfg, year_to: Number(e.target.value) })}
                        className="w-full px-3 py-2 rounded-xl bg-zinc-950 border border-zinc-800 text-xs"
                      />
                    </div>
                    <div>
                      <label className="text-[11px] text-zinc-400 block mb-1">Cylindry</label>
                      <select
                        value={filterCfg.cylinders}
                        onChange={(e) => setFilterCfg({ ...filterCfg, cylinders: e.target.value })}
                        className="w-full px-2 py-2 rounded-xl bg-zinc-950 border border-zinc-800 text-xs"
                      >
                        <option value="6">6 cyl (3.6L)</option>
                        <option value="8">8 cyl (V8)</option>
                        <option value="ALL">Dowolny</option>
                      </select>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-2 items-center">
                    <div>
                      <label className="text-[11px] text-zinc-400 block mb-1">Maks. przebieg (mile)</label>
                      <input
                        type="number"
                        value={filterCfg.max_odometer}
                        onChange={(e) => setFilterCfg({ ...filterCfg, max_odometer: Number(e.target.value) })}
                        className="w-full px-3 py-2 rounded-xl bg-zinc-950 border border-zinc-800 text-xs"
                      />
                    </div>
                    <label className="flex items-center gap-2 text-xs pt-4 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={filterCfg.run_and_drive_only}
                        onChange={(e) => setFilterCfg({ ...filterCfg, run_and_drive_only: e.target.checked })}
                        className="rounded accent-violet-600"
                      />
                      Tylko Run & Drive
                    </label>
                  </div>

                  <div className="p-2.5 rounded-xl bg-zinc-950 border border-zinc-800/80 text-[11px] text-zinc-400 space-y-1">
                    <div className="truncate">
                      <strong className="text-zinc-300">Wygenerowany Copart:</strong>{" "}
                      {generateCopartUrl(filterCfg)}
                    </div>
                    <div className="truncate">
                      <strong className="text-zinc-300">Wygenerowany IAAI:</strong>{" "}
                      {generateIaaiUrl(filterCfg)}
                    </div>
                  </div>
                </div>
              ) : (
                <div className="space-y-2.5 pt-1">
                  <div>
                    <label className="text-[11px] text-zinc-400 block mb-1">
                      Link wyszukiwania Copart (`lotSearchResults?...`):
                    </label>
                    <input
                      type="text"
                      value={filterCfg.copart_url}
                      onChange={(e) => setFilterCfg({ ...filterCfg, copart_url: e.target.value })}
                      className="w-full px-3 py-2 rounded-xl bg-zinc-950 border border-zinc-800 text-xs font-mono"
                    />
                  </div>
                  <div>
                    <label className="text-[11px] text-zinc-400 block mb-1">
                      Link wyszukiwania IAAI (`Search?url=...` lub `Search?keyword=...`):
                    </label>
                    <input
                      type="text"
                      value={filterCfg.iaai_url}
                      onChange={(e) => setFilterCfg({ ...filterCfg, iaai_url: e.target.value })}
                      className="w-full px-3 py-2 rounded-xl bg-zinc-950 border border-zinc-800 text-xs font-mono"
                    />
                  </div>
                </div>
              )}

              {/* AI Color & Tuning Rules */}
              <div className="pt-2 border-t border-zinc-800 space-y-2">
                <label className="text-xs font-semibold block text-zinc-200">
                  Dozwolone kolory dla Gemini AI:
                </label>
                <div className="space-y-1.5">
                  {COLOR_OPTIONS.map((col) => {
                    const checked = filterCfg.allowed_colors.includes(col);
                    return (
                      <label key={col} className="flex items-center gap-2 text-xs text-zinc-300 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={(e) => {
                            const next = e.target.checked
                              ? [...filterCfg.allowed_colors, col]
                              : filterCfg.allowed_colors.filter((c) => c !== col);
                            setFilterCfg({ ...filterCfg, allowed_colors: next });
                          }}
                          className="rounded accent-violet-600"
                        />
                        {col}
                      </label>
                    );
                  })}
                </div>

                <label className="flex items-center gap-2 text-xs text-fuchsia-300 font-medium pt-1 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={filterCfg.allow_modified_any_color}
                    onChange={(e) =>
                      setFilterCfg({ ...filterCfg, allow_modified_any_color: e.target.checked })
                    }
                    className="rounded accent-fuchsia-500"
                  />
                  🔥 Przepuszczaj auta po tuningu / przeróbkach niezależnie od koloru
                </label>
              </div>
            </div>

            {/* Free Firebase Spark Database Connection */}
            <div className="p-4 rounded-2xl bg-zinc-900 border border-zinc-800 space-y-2.5">
              <h3 className="text-sm font-bold flex items-center gap-2 text-white">
                <Database className="w-4 h-4 text-amber-400" />
                Połączenie z darmową bazą Firebase Firestore (Spark $0)
              </h3>
              <p className="text-[11px] text-zinc-400 leading-relaxed">
                Wpisz swój <code>projectId</code> z konsoli Firebase (darmowy plan Spark, bez karty płatniczej).
                Synchronizuje Ulubione, Schowek oraz filtry z GitHub Actions.
              </p>
              <div className="space-y-2">
                <input
                  type="text"
                  placeholder="Firebase Project ID (np. copart-tinder-app)"
                  value={fbProjectId}
                  onChange={(e) => setFbProjectId(e.target.value.trim())}
                  className="w-full px-3 py-2 rounded-xl bg-zinc-950 border border-zinc-800 text-xs font-mono"
                />
                <input
                  type="text"
                  placeholder="Firebase Web API Key (opcjonalnie)"
                  value={fbApiKey}
                  onChange={(e) => setFbApiKey(e.target.value.trim())}
                  className="w-full px-3 py-2 rounded-xl bg-zinc-950 border border-zinc-800 text-xs font-mono"
                />
              </div>
            </div>

            <button
              type="button"
              onClick={async () => {
                saveFirebaseCreds({ projectId: fbProjectId, apiKey: fbApiKey });
                const synced = await saveSearchFilterConfig(filterCfg);
                setSaveBanner(
                  synced
                    ? "Zapisano w Firebase Firestore i pamięci urządzenia!"
                    : "Zapisano lokalnie (podaj Firebase Project ID powyżej, aby synchronizować w chmurze)."
                );
                setTimeout(() => setSaveBanner(null), 4000);
              }}
              className="w-full py-3 rounded-2xl bg-gradient-to-r from-violet-600 to-fuchsia-600 text-white font-bold text-xs shadow-lg shadow-violet-600/25 hover:opacity-95 active:scale-98 transition"
            >
              Zapisz ustawienia i filtry
            </button>
          </div>
        )}
      </main>

      {/* Bottom Navigation Bar */}
      <nav className="fixed bottom-0 left-0 right-0 max-w-md mx-auto bg-zinc-950/95 backdrop-blur border-t border-zinc-900 px-2 py-2 flex items-center justify-around z-30">
        <button
          onClick={() => setActiveTab("swipe")}
          className={`flex flex-col items-center gap-1 px-3 py-1.5 rounded-xl text-xs font-semibold transition ${
            activeTab === "swipe" ? "text-violet-400" : "text-zinc-500 hover:text-zinc-300"
          }`}
        >
          <Flame className="w-5 h-5" />
          <span>Swipe ({unswipedCars.length})</span>
        </button>

        <button
          onClick={() => setActiveTab("liked")}
          className={`flex flex-col items-center gap-1 px-3 py-1.5 rounded-xl text-xs font-semibold transition ${
            activeTab === "liked" ? "text-emerald-400" : "text-zinc-500 hover:text-zinc-300"
          }`}
        >
          <Heart className="w-5 h-5" />
          <span>Ulubione ({likedCars.length})</span>
        </button>

        <button
          onClick={() => setActiveTab("archived")}
          className={`flex flex-col items-center gap-1 px-3 py-1.5 rounded-xl text-xs font-semibold transition ${
            activeTab === "archived" ? "text-rose-400" : "text-zinc-500 hover:text-zinc-300"
          }`}
        >
          <Archive className="w-5 h-5" />
          <span>Schowek ({archivedCars.length})</span>
        </button>

        <button
          onClick={() => setActiveTab("settings")}
          className={`flex flex-col items-center gap-1 px-3 py-1.5 rounded-xl text-xs font-semibold transition ${
            activeTab === "settings" ? "text-amber-400" : "text-zinc-500 hover:text-zinc-300"
          }`}
        >
          <SlidersHorizontal className="w-5 h-5" />
          <span>Filtry</span>
        </button>
      </nav>
    </div>
  );
}
