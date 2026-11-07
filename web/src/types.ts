export interface CarListing {
  id: string;
  found_at: string;
  source: "Copart" | "IAAI" | string;
  lot_id: string;
  vin: string;
  title: string;
  color: string;
  color_approved?: boolean;
  is_modified: boolean;
  modifications: string;
  damage_assessment: string;
  url: string;
  price_check_url: string;
  image_urls: string[];
}

export type SwipeDecision = "liked" | "archived";

export interface SwipeRecord {
  carId: string;
  decision: SwipeDecision;
  swipedAt: string;
  note?: string;
}

export interface SearchFilterConfig {
  use_custom_urls: boolean;
  make: string;
  model: string;
  year_from: number;
  year_to: number;
  max_odometer: number;
  cylinders: string;
  run_and_drive_only: boolean;
  allowed_colors: string[];
  allow_modified_any_color: boolean;
  copart_url: string;
  iaai_url: string;
}
